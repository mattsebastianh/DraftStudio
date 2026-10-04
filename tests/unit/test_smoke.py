def test_dependencies_importable():
    from importlib.metadata import version

    import jsonschema
    import yaml

    assert version("jsonschema")
    assert yaml.safe_load("a: 1") == {"a": 1}


def test_harness_package_importable():
    import harness

    assert harness.__doc__
