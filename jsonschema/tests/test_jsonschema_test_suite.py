"""
Test runner for the JSON Schema official test suite

Tests comprehensive correctness of each draft's validator.

See https://github.com/json-schema/JSON-Schema-Test-Suite for details.

"""

from decimal import Decimal
import sys
import unittest
import os
import json
import re

from jsonschema import (
    FormatError, SchemaError, ValidationError, Draft3Validator,
    Draft4Validator, FormatChecker, draft3_format_checker,
    draft4_format_checker, validate,
)
from jsonschema.compat import PY3
from jsonschema.tests.compat import mock
from jsonschema.tests._suite import Suite


SUITE = Suite()
DRAFT3 = SUITE.collection(name="draft3")
DRAFT4 = SUITE.collection(name="draft4")


def maybe_skip(skip, test_case, test):
    if skip is not None:
        reason = skip(test)
        if reason is not None:
            test_case = unittest.skip(reason)(test_case)
    return test_case


def load_json_cases(tests, skip=None):
    def add_test_methods(test_class):
        for test in tests:
            test = test.with_validate_kwargs(
                **getattr(test_class, "validator_kwargs", {})
            )
            method = test.to_unittest_method()
            assert not hasattr(test_class, method.__name__), test
            setattr(
                test_class,
                method.__name__,
                maybe_skip(skip, method, test),
            )

        return test_class
    return add_test_methods


def load_meta_cases(meta_tests_file, basedir=os.path.join(SUITE, "tests")):
    def add_test_methods(test_class):
        with open(os.path.join(basedir, meta_tests_file)) as test_file:
            for case in json.load(test_file):
                for (idx, test) in enumerate(case["tests"]):
                    name = "test_meta_%s_%s_%s" % (
                        re.sub(r"[\W ]+", "_", case["description"]),
                        idx,
                        re.sub(r"[\W ]+", "_", test["description"]),
                    )
                    assert not hasattr(test_class, name), name
                    test_method = create_meta_test(test["schema"])
                    setattr(test_class, name, test_method)
        return test_class
    return add_test_methods


def create_meta_test(schema):
    def test(self):
        kwargs = getattr(self, "validator_kwargs", {})
        with self.assertRaises(SchemaError):
            validate({}, schema, cls=self.validator_class, **kwargs)
    return test


def skip_tests_containing_descriptions(descriptions_and_reasons):
    def skipper(test):
        return next(
            (
                reason
                for description, reason in descriptions_and_reasons.items()
                if description in test.description
            ),
            None,
        )
    return skipper


class TypesMixin(object):
    @unittest.skipIf(PY3, "In Python 3 json.load always produces unicode")
    def test_string_a_bytestring_is_a_string(self):
        self.validator_class({"type": "string"}).validate(b"foo")


class DecimalMixin(object):
    def test_it_can_validate_with_decimals(self):
        schema = {"type": "number"}
        validator = self.validator_class(
            schema, types={"number": (int, float, Decimal)}
        )

        for valid in [1, 1.1, Decimal(1) / Decimal(8)]:
            validator.validate(valid)

        for invalid in ["foo", {}, [], True, None]:
            with self.assertRaises(ValidationError):
                validator.validate(invalid)


def missing_format(checker):
    def missing_format(test):
        format = test.schema.get("format")
        if format not in checker.checkers:
            return "Format checker {0!r} not found.".format(format)
    return missing_format


class FormatMixin(object):
    def test_it_returns_true_for_formats_it_does_not_know_about(self):
        validator = self.validator_class(
            {"format": "carrot"}, format_checker=FormatChecker(),
        )
        validator.validate("bugs")

    def test_it_does_not_validate_formats_by_default(self):
        validator = self.validator_class({})
        self.assertIsNone(validator.format_checker)

    def test_it_validates_formats_if_a_checker_is_provided(self):
        checker = mock.Mock(spec=FormatChecker)
        validator = self.validator_class(
            {"format": "foo"}, format_checker=checker,
        )

        validator.validate("bar")

        checker.check.assert_called_once_with("bar", "foo")

        cause = ValueError()
        checker.check.side_effect = FormatError("aoeu", cause=cause)

        with self.assertRaises(ValidationError) as cm:
            validator.validate("bar")
        # Make sure original cause is attached
        self.assertIs(cm.exception.cause, cause)

    def test_it_validates_formats_of_any_type(self):
        checker = mock.Mock(spec=FormatChecker)
        validator = self.validator_class(
            {"format": "foo"}, format_checker=checker,
        )

        validator.validate([1, 2, 3])

        checker.check.assert_called_once_with([1, 2, 3], "foo")

        cause = ValueError()
        checker.check.side_effect = FormatError('aoeu', cause=cause)

        with self.assertRaises(ValidationError) as cm:
            validator.validate([1, 2, 3])
        # Make sure original cause is attached
        self.assertIs(cm.exception.cause, cause)


if sys.maxunicode == 2 ** 16 - 1:          # This is a narrow build.
    narrow_unicode_build = skip_tests_containing_descriptions(
        {
            "supplementary Unicode":
                "Not running surrogate Unicode case, this Python is narrow.",
        }
    )
else:
    def narrow_unicode_build(test):  # This isn't, skip nothing.
        return


@load_json_cases(
    tests=(test for test in DRAFT3.tests() if test.subject != "refRemote"),
    skip=narrow_unicode_build,
)
@load_json_cases(
    tests=DRAFT3.optional_tests_of(name="format"),
    skip=missing_format(draft3_format_checker),
)
@load_json_cases(tests=DRAFT3.optional_tests_of(name="bignum"))
@load_json_cases(tests=DRAFT3.optional_tests_of(name="zeroTerminatedFloats"))
class TestDraft3(unittest.TestCase, TypesMixin, DecimalMixin, FormatMixin):
    validator_class = Draft3Validator
    validator_kwargs = {"format_checker": draft3_format_checker}

    def test_any_type_is_valid_for_type_any(self):
        validator = self.validator_class({"type": "any"})
        validator.validate(mock.Mock())

    # TODO: we're in need of more meta schema tests
    def test_invalid_properties(self):
        with self.assertRaises(SchemaError):
            validate({}, {"properties": {"test": True}},
                     cls=self.validator_class)

    def test_minItems_invalid_string(self):
        with self.assertRaises(SchemaError):
            # needs to be an integer
            validate([1], {"minItems": "1"}, cls=self.validator_class)


@load_json_cases(
    tests=(test for test in DRAFT4.tests() if test.subject != "refRemote"),
    skip=lambda test: (
        narrow_unicode_build(test) or skip_tests_containing_descriptions(
            {
                "valid tree":  "An actual bug, this needs fixing.",
            },
        )(test)
    ),
)
@load_json_cases(
    tests=DRAFT4.optional_tests_of(name="format"),
    skip=missing_format(draft4_format_checker),
)
@load_json_cases(tests=DRAFT4.optional_tests_of(name="bignum"))
@load_json_cases(tests=DRAFT4.optional_tests_of(name="zeroTerminatedFloats"))
@load_meta_cases("draft4/meta/meta.json")
class TestDraft4(unittest.TestCase, TypesMixin, DecimalMixin, FormatMixin):
    validator_class = Draft4Validator
    validator_kwargs = {"format_checker": draft4_format_checker}


@load_json_cases(tests=DRAFT3.tests_of(name="refRemote"))
class Draft3RemoteResolution(unittest.TestCase):
    validator_class = Draft3Validator


@load_json_cases(
    tests=DRAFT4.tests_of(name="refRemote"),
    skip=skip_tests_containing_descriptions(
        {
            "number is valid": "An actual bug, this needs fixing.",
            "string is invalid": "An actual bug, this needs fixing.",
        },
    ),
)
class Draft4RemoteResolution(unittest.TestCase):
    validator_class = Draft4Validator
