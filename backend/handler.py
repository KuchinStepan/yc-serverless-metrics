import json
import os
import ydb
import ydb.iam

TABLE = "metrics"
VERSION = os.getenv("BACKEND_VERSION", "default")


def response(status_code, body):
    return {
        'statusCode': status_code,
        'body': json.dumps(body) if isinstance(body, (dict, list)) else str(body),
    }


def get_driver():
    endpoint = os.getenv("endpoint")
    database = os.getenv("database")

    if not all([endpoint, database]):
        raise ValueError("Missing required environment variables 'endpoint' or 'database'")

    credentials = ydb.iam.ServiceAccountCredentials.from_file("auth.sa")
    conf = ydb.DriverConfig(endpoint, database, credentials=credentials)
    driver = ydb.Driver(conf)
    # дождёмся готовности драйвера
    driver.wait(timeout=5)
    return driver


def create_table(session):
    # таблица: metricName как PRIMARY KEY, счетчик count (Uint64), время создания
    query = f"""
    CREATE TABLE `{TABLE}` (
        metricName Text,
        count Uint64,
        creation_time Timestamp,
        PRIMARY KEY (metricName)
    )
    WITH (
        AUTO_PARTITIONING_BY_SIZE = ENABLED,
        AUTO_PARTITIONING_PARTITION_SIZE_MB = 1024
    );
    """
    session.execute_scheme(query)
    print(f"Таблица '{TABLE}' создана")


def create_schema():
    driver = get_driver()
    try:
        with ydb.SessionPool(driver) as pool:
            pool.retry_operation_sync(create_table)
        return "Schema created successfully"
    finally:
        driver.stop()


def handler(event, context):
    """
    Ожидается POST с JSON телом: {"metricName": "имя_метрики"}
    если MODE=init -> создаёт схему
    """
    if event.get("MODE") == "init":
        return response(200, create_schema())

    driver = get_driver()
    try:
        with ydb.SessionPool(driver) as pool:
            if event.get("httpMethod") != "POST":
                return response(405, "Method Not Allowed")

            body = json.loads(event.get("body", "{}"))
            metric_name = body.get("metricName")
            if not metric_name or not isinstance(metric_name, str):
                return response(400, {"error": "metricName is required and must be a string"})

            if len(metric_name) > 255:
                # ограничение произвольно — подберите своё
                return response(400, {"error": "metricName too long"})

            def upsert_metric(session):
                # Создаём транзакцию в режиме изменений (serializable read-write)
                tx = session.transaction(ydb.SerializableReadWrite())
                try:
                    # 1) читаем существующий счётчик (внутри транзакции)
                    select_q = """
                        DECLARE $metric AS Text;
                        SELECT count FROM `{table}` WHERE metricName = $metric;
                    """.format(table=TABLE)

                    prepared_query = session.prepare(select_q)
                    result_sets = tx.execute(
                        prepared_query,
                        parameters={'$metric': metric_name}
                    )

                    rows = []
                    if result_sets and len(result_sets) > 0:
                        # .rows — коллекция строк; каждое поле доступно по имени
                        rows = list(result_sets[0].rows)

                    if rows:
                        # строка есть -> обновляем, увеличивая на 1
                        update_q = """
                            DECLARE $metric AS Text;
                            UPDATE `{table}` SET count = count + 1 WHERE metricName = $metric;
                        """.format(table=TABLE)

                        prepared_update = session.prepare(update_q)
                        tx.execute(
                            prepared_update,
                            parameters={'$metric': metric_name}
                        )

                        # можно вернуть новый value с отдельным SELECT, но чтобы не делать ещё one round-trip,
                        # можно считать, что значение увеличено успешно
                        tx.commit()
                        return response(200, {"status": "incremented", "metric": metric_name})

                    else:
                        # нет строки -> вставляем новую с count = 1
                        insert_q = """
                            DECLARE $metric AS Text;
                            INSERT INTO `{table}` (metricName, count, creation_time)
                            VALUES ($metric, 1, CurrentUtcTimestamp());
                        """.format(table=TABLE)

                        prepared_insert = session.prepare(insert_q)
                        tx.execute(
                            prepared_insert,
                            parameters={'$metric': metric_name}
                        )
                        tx.commit()
                        return response(201, {"status": "created", "metric": metric_name, "count": 1})

                except Exception:
                    # при ошибке откатим транзакцию и пробросим дальше
                    try:
                        tx.rollback()
                    except Exception:
                        pass
                    raise

            # выполняем с автоматическим ретраем с пула сессий
            return pool.retry_operation_sync(upsert_metric)

    except Exception as e:
        return response(500, {"error": str(e)})
    finally:
        driver.stop()
