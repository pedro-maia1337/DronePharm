import os
import sys
from datetime import datetime, timezone

import pytest
from pydantic import ValidationError

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from server.schemas.schemas import PedidoUpdate
from server.utils.datetime_utils import parse_datetime_utc


def test_parse_datetime_utc_converte_iso_com_timezone():
    parsed = parse_datetime_utc("2026-06-01T18:00:00-03:00")

    assert parsed == datetime(2026, 6, 1, 21, 0, tzinfo=timezone.utc)


def test_pedido_update_rejeita_janela_fim_sem_timezone():
    with pytest.raises(ValidationError) as exc_info:
        PedidoUpdate(janela_fim="2026-06-01T18:00:00")

    assert "ISO 8601 com timezone" in str(exc_info.value)
