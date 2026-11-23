import os
os.environ['PAINTMINT_LANG'] = 'en'   # las pruebas se ejecutan siempre en inglés
os.environ.setdefault('PAINTMINT_NO_DESKTOP', '1')
os.environ.setdefault('PAINTMINT_NO_UPDATE_CHECK', '1')   # las pruebas nunca tocan la red
os.environ.setdefault('XDG_CONFIG_HOME', os.path.join(__import__('tempfile').gettempdir(), 'paintmint-test-config'))
import os
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np
import pytest

from paintmint.core.document import Document
from paintmint.core.session import EditSession
from paintmint.tools import ToolContext, ToolOptions, create_tools


@pytest.fixture
def session():
    return EditSession(Document(100, 80))


@pytest.fixture
def ctx(session):
    return ToolContext(session, ToolOptions())


@pytest.fixture
def tools():
    return create_tools()


def px(session, x, y, layer=None):
    layer = layer or session.active_layer
    return tuple(int(v) for v in layer.pixels[y, x])
