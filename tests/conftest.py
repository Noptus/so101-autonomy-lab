import pytest
from so101_lab.lab import Lab


@pytest.fixture
def lab(tmp_path):
    instance = Lab(tmp_path, realtime=False)
    yield instance
    instance.close()
