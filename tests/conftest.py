import os


def pytest_configure(config):
    """Set dummy AWS credentials before any test modules are imported."""
    os.environ.setdefault('AWS_DEFAULT_REGION', 'us-east-1')
    os.environ.setdefault('AWS_ACCESS_KEY_ID', 'testing')
    os.environ.setdefault('AWS_SECRET_ACCESS_KEY', 'testing')
    os.environ.setdefault('AWS_SECURITY_TOKEN', 'testing')
    os.environ.setdefault('AWS_SESSION_TOKEN', 'testing')
