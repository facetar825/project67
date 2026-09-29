import pytest
from domain import level, validate_text, RuleError


@pytest.mark.parametrize('xp,expected',[(0,1),(199,1),(200,2),(400,3)])
def test_levels(xp,expected):
    assert level(xp)==expected


def test_empty_name_rejected():
    with pytest.raises(RuleError): validate_text('  ','Имя',80)


def test_normalize_name():
    assert validate_text('  Учёба  ','Имя',80)=='Учёба'
