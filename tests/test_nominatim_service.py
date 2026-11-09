from service.nominatim import LAYERS
from strag_v3.place import ANY, KINDS


def test_layers_cover_every_kind():
    assert set(LAYERS) == {*KINDS, ANY}
