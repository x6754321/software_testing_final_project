"""CLI argument parsing related tests."""
import argparse
import json

import pytest
from requests.exceptions import InvalidSchema

import httpie.cli.argparser
from fixtures import (
    FILE_CONTENT, FILE_PATH, FILE_PATH_ARG, JSON_FILE_CONTENT,
    JSON_FILE_PATH_ARG,
)
from httpie.status import ExitStatus
from httpie.cli import constants
from httpie.cli.definition import parser
from httpie.cli.argtypes import KeyValueArg, KeyValueArgType
from httpie.cli.requestitems import RequestItems
from utils import HTTP_OK, MockEnvironment, http


class TestItemParsing:
    key_value_arg = KeyValueArgType(*constants.SEPARATOR_GROUP_ALL_ITEMS)

    def test_invalid_items(self):
        items = ['no-separator']
        for item in items:
            pytest.raises(argparse.ArgumentTypeError, self.key_value_arg, item)

    def test_escape_separator(self):
        items = RequestItems.from_args([
            # headers
            self.key_value_arg(r'foo\:bar:baz'),
            self.key_value_arg(r'jack\@jill:hill'),

            # data
            self.key_value_arg(r'baz\=bar=foo'),

            # files
            self.key_value_arg(r'bar\@baz@%s' % FILE_PATH_ARG),
        ])
        # `requests.structures.CaseInsensitiveDict` => `dict`
        headers = dict(items.headers._store.values())

        assert headers == {
            'foo:bar': 'baz',
            'jack@jill': 'hill',
        }
        assert items.data == {
            'baz=bar': 'foo'
        }
        assert 'bar@baz' in items.files

    @pytest.mark.parametrize(('string', 'key', 'sep', 'value'), [
        ('path=c:\\windows', 'path', '=', 'c:\\windows'),
        ('path=c:\\windows\\', 'path', '=', 'c:\\windows\\'),
        ('path\\==c:\\windows', 'path=', '=', 'c:\\windows'),
    ])
    def test_backslash_before_non_special_character_does_not_escape(
        self, string, key, sep, value
    ):
        expected = KeyValueArg(orig=string, key=key, sep=sep, value=value)
        actual = self.key_value_arg(string)
        assert actual == expected

    def test_escape_longsep(self):
        items = RequestItems.from_args([
            self.key_value_arg(r'bob\:==foo'),
        ])
        assert items.params == {
            'bob:': 'foo'
        }

    def test_valid_items(self):
        items = RequestItems.from_args([
            self.key_value_arg('string=value'),
            self.key_value_arg('Header:value'),
            self.key_value_arg('Unset-Header:'),
            self.key_value_arg('Empty-Header;'),
            self.key_value_arg('list:=["a", 1, {}, false]'),
            self.key_value_arg('obj:={"a": "b"}'),
            self.key_value_arg('ed='),
            self.key_value_arg('bool:=true'),
            self.key_value_arg('file@' + FILE_PATH_ARG),
            self.key_value_arg('query==value'),
            self.key_value_arg('string-embed=@' + FILE_PATH_ARG),
            self.key_value_arg('raw-json-embed:=@' + JSON_FILE_PATH_ARG),
        ])

        # Parsed headers
        # `requests.structures.CaseInsensitiveDict` => `dict`
        headers = dict(items.headers._store.values())
        assert headers == {
            'Header': 'value',
            'Unset-Header': None,
            'Empty-Header': ''
        }

        # Parsed data
        raw_json_embed = items.data.pop('raw-json-embed')
        assert raw_json_embed == json.loads(JSON_FILE_CONTENT)
        items.data['string-embed'] = items.data['string-embed'].strip()
        assert dict(items.data) == {
            "ed": "",
            "string": "value",
            "bool": True,
            "list": ["a", 1, {}, False],
            "obj": {
                "a": "b"
            },
            "string-embed": FILE_CONTENT,
        }

        # Parsed query string parameters
        assert items.params == {
            'query': 'value'
        }

        # Parsed file fields
        assert 'file' in items.files
        assert (items.files['file'][1].read().strip().
                decode('utf8') == FILE_CONTENT)

    def test_multiple_file_fields_with_same_field_name(self):
        items = RequestItems.from_args([
            self.key_value_arg('file_field@' + FILE_PATH_ARG),
            self.key_value_arg('file_field@' + FILE_PATH_ARG),
        ])
        assert len(items.files['file_field']) == 2

    def test_multiple_text_fields_with_same_field_name(self):
        items = RequestItems.from_args(
            request_item_args=[
                self.key_value_arg('text_field=a'),
                self.key_value_arg('text_field=b')
            ],
            as_form=True,
        )
        assert items.data['text_field'] == ['a', 'b']
        assert list(items.data.items()) == [
            ('text_field', 'a'),
            ('text_field', 'b'),
        ]