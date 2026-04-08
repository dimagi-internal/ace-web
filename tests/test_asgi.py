def test_asgi_application_loads():
    from config.asgi import application

    assert application is not None
