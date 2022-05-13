""" Code dedicated to types and type annotations handling. """

#
# NOTE #1: the file is named _typing.py - note the leading underscore - on purpose,
# to avoid any conflict with standard library's typing module.
#
# NOTE #2: code in this file may, at some point, require access to some types defined
# in tmt codebase. These imports must be done locally, because this file is supposed
# to be imported by tmt code, and local imports are necessary to avoid circular imports.
# It's not a perfect solution, but the code below is complex, lengthy and dedicated to
# one topic, moving it into its own module should make it easier to maintain.
#

import sys
from typing import (TYPE_CHECKING, Any, Dict, Generator, List, Optional, Tuple,
                    Type, Union, cast)

import fmf

if TYPE_CHECKING:
    from tmt.base import FmfIdType
    from tmt.utils import BaseLoggerFnType


# TODO: refactor all these conditions into a nice and easy-to-use helpers
if sys.version_info.minor >= 8:
    from typing import Literal, TypedDict

else:
    from typing_extensions import Literal  # type: ignore[misc]
    from typing_extensions import TypedDict

if sys.version_info.minor == 6:
    from typing import _ForwardRef as ForwardRef  # type: ignore[attr-defined]

    from typing_extensions import _Literal  # type: ignore[attr-defined]

else:
    from typing import ForwardRef


# A type describing core `link` attribute. See https://tmt.readthedocs.io/en/stable/spec/core.html#link
# for its formal specification, the gist is: there can be several
# combinations of various data structures.

# TODO: `*tmt.base.Link._relations` would be much better, DRY, but that's allowed
# since Python 3.11.
_RawLinkRelationType = Literal[
    'verifies', 'verified-by',
    'implements', 'implemented-by',
    'documents', 'documented-by',
    'blocks', 'blocked-by',
    'duplicates', 'duplicated-by',
    'parent', 'child',
    'relates',
    # Special case: not a relation, but it can appear where relations appear in
    # link data structures.
    'note'
]

# A "relation": "link" subtype.
#
# An example from TMT docs says:
#
# link:
#   verifies: /stories/cli/init/base
#
# link:
#     blocked-by:
#         url: https://github.com/teemtee/fmf
#         name: /stories/select/filter/regexp
#     note: Need to get the regexp filter working first.

_RawLinkRelationAwareType = Dict[_RawLinkRelationType, Union[str, 'FmfIdType']]

_RawLinkType = Union[
    # link: https://github.com/teemtee/tmt/issues/461
    str,
    'FmfIdType',
    _RawLinkRelationAwareType,

    # link:
    # - verifies: /stories/cli/init/base
    # - verifies: https://bugzilla.redhat.com/show_bug.cgi?id=1234
    List[Union[str, 'FmfIdType', _RawLinkRelationAwareType]],
]


_RawFmfIdType = Dict[str, Optional[str]]


if sys.version_info.minor == 6:
    def evaluate_forward_ref(ref: ForwardRef) -> type:
        from tmt.base import FmfIdType, Link

        return cast(type, ref._eval_type(globals(), locals()))

elif sys.version_info.minor == 7:
    def evaluate_forward_ref(ref: ForwardRef) -> type:
        from tmt.base import FmfIdType, Link

        return cast(type, ref._evaluate(globals(), locals()))

else:
    def evaluate_forward_ref(ref: ForwardRef) -> type:
        from tmt.base import FmfIdType, Link

        return cast(type, ref._evaluate(globals(), locals(), frozenset()))


def is_list(type_: type) -> bool:
    """ Decide whether the given type is a list or not. """

    return getattr(type_, '__origin__', None) in (list, List)


def extract_list_members(type_: type) -> Tuple[type]:
    assert hasattr(type_, '__args__')

    return (type_.__args__[0],)  # type: ignore[attr-defined]


def is_dict(type_: type) -> bool:
    """ Decide whether the given type is a dictionary or not. """

    return getattr(type_, '__origin__', None) in (dict, Dict)


def extract_dict_members(type_: type) -> Tuple[type, type]:
    assert hasattr(type_, '__args__')

    return (type_.__args__[0], type_.__args__[1])  # type: ignore[attr-defined]


def is_union(type_: type) -> bool:
    """ Decide whether the given type is an union or not. """

    # According to typing.py, special typing constructs like Union or Optional have
    # __origin__ attribute, holding the original subscripted type.
    return getattr(type_, '__origin__', None) is Union


def extract_union_members(type_: type) -> Tuple[type, ...]:
    assert hasattr(type_, '__args__')

    return cast(Tuple[type, ...], type_.__args__)  # type: ignore[attr-defined]


def is_literal(type_: type) -> bool:
    """ Decide whether the given type is a literal or not. """

    if getattr(type_, '__origin__', None) is Literal:
        return True

    if sys.version_info.minor == 6:
        return isinstance(type_, _Literal)

    return False


def extract_literal_members(type_: type) -> List[Any]:
    if sys.version_info.minor == 6:
        return cast(List[Any], type_.__values__)  # type: ignore[attr-defined]

    return cast(List[Any], type_.__args__)  # type: ignore[attr-defined]


def is_link(type_: type) -> bool:
    """ Decide whether the given type is a tmt.base.Link or not. """

    from tmt.base import Link

    return type_ is Link


def is_fmf_id(type_: type) -> bool:
    """ Decide whether the given type is a tmt.base.FmfIdType or not. """

    from tmt.base import FmfIdType

    return type_ is FmfIdType


def format_type(type_: type) -> str:
    """ Helper providing reasonably well formatted name of a given type. """

    if isinstance(None, type_):
        return 'null'

    if is_list(type_):
        vt = extract_list_members(type_)[0]

        return f'list of ({format_type(vt)})'

    if is_dict(type_):
        kt, vt = extract_dict_members(type_)

        return f'mapping ({format_type(kt)}:{format_type(vt)})'

    if is_literal(type_):
        return ' or '.join(
            f'"{item}"' for item in extract_literal_members(type_))

    if is_union(type_):
        return ' or '.join(format_type(component_type)
                           for component_type in extract_union_members(type_))

    if is_link(type_):
        return 'Fmf link'

    if is_fmf_id(type_):
        return 'Fmf id'

    if type_ == str:
        return 'string'

    if type_ == list:
        return 'list'

    if type_ == dict:
        return 'mapping'

    if type_ == bool:
        return 'boolean'

    if type_ == int:
        return 'integer'

    if type_ == float:
        return 'floating-point number'

    if isinstance(type_, ForwardRef):
        return format_type(evaluate_forward_ref(type_))

    raise NotImplementedError(
        f'type {type_} has no human-readable description')


def _check_list(
    logger: 'BaseLoggerFnType',
    address: str,
    shift: int,
    value: Any,
    expected_type: type,
    errors: List[str]
) -> bool:
    """
    Verify that a given value matches expected type, where expected type is
    a list of items.

    Args:
      parent: an object owning the key that's being validated.
      address: location of the value within its container(s). Used to provide better
          location when reporting issues.
      shift: how far should be log messages indented.
      value: an object to validate.
      expected_type: a type ``value`` is supposed to be of.
      errors: accumulator for errors found during validation process.

    Returns:
      ``True`` when validation succeeded, ``False`` otherwise.
    """

    actual_type = type(value)

    logger(
        '_check_list',
        f'{value} of type {format_type(actual_type)}, expected to be {format_type(expected_type)}',
        shift=shift)

    if not isinstance(value, list):
        errors.append(
            f'{address} expected to be {format_type(expected_type)}, found {format_type(actual_type)}')

        return False

    if not len(value):
        logger('_check_list', 'no items detected', shift=shift)

        return True

    args = getattr(expected_type, '__args__', [])

    if not args:
        raise NotImplementedError(
            f'Type >>{actual_type}<< not recognized as list')

    vt = args[0]

    if vt is Any:
        return True

    for i, v in enumerate(value):
        if not check_type(
            logger,
            f'{address}[{i}]',
            shift + 1,
            v,
            vt,
                errors):
            errors.append(
                f'value of {address}[{i}] expected to be {format_type(vt)}, found {format_type(type(v))}')

            return False

    return True


def _check_dict(
    logger: 'BaseLoggerFnType',
    address: str,
    shift: int,
    value: Any,
    expected_type: type,
    errors: List[str]
) -> bool:
    """
    Verify that a given value matches expected type, where expected type is
    a dictionary.

    Args:
      parent: an object owning the key that's being validated.
      address: location of the value within its container(s). Used to provide better
          location when reporting issues.
      shift: how far should be log messages indented.
      value: an object to validate.
      expected_type: a type ``value`` is supposed to be of.
      errors: accumulator for errors found during validation process.

    Returns:
      ``True`` when validation succeeded, ``False`` otherwise.
    """

    actual_type = type(value)

    logger(
        '_check_dict',
        f'{value} of type {format_type(actual_type)}, expected to be {format_type(expected_type)}',
        shift=shift)

    if not isinstance(value, dict):
        errors.append(
            f'{address} expected to be {format_type(expected_type)}, found {format_type(actual_type)}')

        return False

    if not len(value):
        logger('_check_dict', 'no items detected', shift=shift)

        return True

    args = getattr(expected_type, '__args__', [])

    if len(args) != 2:
        raise NotImplementedError(
            f'Type >>{actual_type}<< not recognized as dict')

    kt = args[0]
    vt = args[1]

    for k, v in value.items():
        if kt is not Any and not check_type(
                logger, f'{address}, key {k}', shift + 1, k, kt, errors):
            errors.append(
                f'key "{k}" in {address} expected to be {format_type(kt)}, found {format_type(type(k))}')

            return False

        if vt is not Any and not check_type(
                logger, f'{address}[{k}]', shift + 1, v, vt, errors):
            errors.append(
                f'value of {address}[{k}] expected to be "{format_type(vt)}", found {format_type(type(v))}')

            return False

    return True


def _check_union(
    logger: 'BaseLoggerFnType',
    address: str,
    shift: int,
    value: Any,
    expected_type: type,
    errors: List[str]
) -> bool:
    """
    Verify that a given value matches expected type, where expected type is
    an Union of multiple allowed types.

    Args:
      parent: an object owning the key that's being validated.
      address: location of the value within its container(s). Used to provide better
          location when reporting issues.
      shift: how far should be log messages indented.
      value: an object to validate.
      expected_type: a type ``value`` is supposed to be of.
      errors: accumulator for errors found during validation process.

    Returns:
      ``True`` when validation succeeded, ``False`` otherwise.
    """

    actual_type = type(value)

    logger(
        '_check_union',
        f'{value} of type {format_type(actual_type)}, expected to be {format_type(expected_type)}',
        shift=shift)

    if any(check_type(logger, address, shift + 1, value, component_type, errors)
           for component_type in extract_union_members(expected_type)):
        return True

    errors.append(
        f'value of {address} expected to be {format_type(expected_type)}, found {format_type(actual_type)}')

    return False


def check_type(
    logger: 'BaseLoggerFnType',
    address: str,
    shift: int,
    value: Any,
    expected_type: type,
    errors: List[str]
) -> bool:
    """
    Verify that a given value matches expected type.

    This is the main entrypoint of "verify type" functions, and dispatches
    calls to other functions for more specific types as needed.

    Args:
      parent: an object owning the key that's being validated.
      address: location of the value within its container(s). Used to provide better
          location when reporting issues.
      shift: how far should be log messages indented.
      value: an object to validate.
      expected_type: a type ``value`` is supposed to be of.
      errors: accumulator for errors found during validation process.

    Returns:
      ``True`` when validation succeeded, ``False`` otherwise.
    """

    if isinstance(expected_type, ForwardRef):
        logger(
            '_check_type',
            f'detected forward reference >>{expected_type}<<',
            shift=shift)

        return check_type(
            logger,
            address,
            shift + 1,
            value,
            evaluate_forward_ref(expected_type),
            errors
            )

    actual_type = type(value)

    logger(
        '_check_type',
        f'{value} of type {format_type(actual_type)}, expected to be {format_type(expected_type)}',
        shift=shift)

    if is_list(expected_type):
        return _check_list(
            logger,
            address,
            shift + 1,
            value,
            expected_type,
            errors)

    if is_dict(expected_type):
        return _check_dict(
            logger,
            address,
            shift + 1,
            value,
            expected_type,
            errors)

    if is_literal(expected_type):
        return value in extract_literal_members(expected_type)

    if is_union(expected_type):
        return _check_union(
            logger,
            address,
            shift + 1,
            value,
            expected_type,
            errors)

    if is_link(expected_type):
        logger('_check_type', f'detected link type', shift=shift)

        return check_type(
            logger,
            address,
            shift + 1,
            value,
            _RawLinkType,  # type: ignore[arg-type]
            errors)

    if is_fmf_id(expected_type):
        logger('_check_type', f'detected fmf id type', shift=shift)

        return check_type(
            logger,
            address,
            shift + 1,
            value,
            _RawFmfIdType,
            errors)

    if isinstance(value, expected_type):
        return True

    # WARNING: not all types are supported! The extent of support is dictated
    # by needs of classes derived from tmt.base.Core and keys they wish to
    # import from fmf.Tree objects they own. When encountering a perfectly legal
    # type being not supported yet, feel free to implement necessary checks.

    # errors.append(f'{address}: expected type {format_type(expected_type)}, found {format_type(actual_type)}')
    # raise NotImplementedError(f'type {format_type(expected_type)} is not supported')

    return False


class DeclarativeKeys:
    """ Mixin adding support for Fmf-backed keys with declared types. """

    KEYS_SHOW_ORDER: List[str] = []

    def _iter_key_annotations(self) -> Generator[Tuple[str, Any], None, None]:
        """
        Iterate over keys' type annotations.

        Keys are yielded in the order: keys declared by parent classes, then
        keys declared by the class itself.

        Yields:
            pairs of key name and its annotations.
        """

        for base in self.__class__.__bases__:
            yield from base.__dict__.get('__annotations__', {}).items()

        yield from self.__class__.__dict__.get('__annotations__', {}).items()

    def iter_key_names(self) -> Generator[str, None, None]:
        """
        Iterate over key names.

        Keys are yielded in the order: keys declared by parent classes, then
        keys declared by the class itself.

        Yields:
            key names.
        """

        for keyname, _ in self._iter_key_annotations():
            yield keyname

    def iter_keys(self) -> Generator[Tuple[str, Any], None, None]:
        """
        Iterate over keys and their values.

        Keys are yielded in the order: keys declared by parent classes, then
        keys declared by the class itself.

        Yields:
            pairs of key name and its value.
        """

        for keyname in self.iter_key_names():
            yield (keyname, getattr(self, keyname))

    # TODO: exists for backward compatibility for the transition period. Once full
    # type annotations land, there should be no need for extra _keys attribute.
    @property
    def _keys(self) -> List[str]:
        """ Return a list of names of object's keys. """

        return list(self.iter_key_names())

    def _extract_keys(
            self,
            node: fmf.Tree,
            logger: 'BaseLoggerFnType') -> None:
        """ Extract values for class-level attributes, and verify they match declared types. """

        import tmt.base
        import tmt.utils

        logger('key validation', node.name)

        for keyname, keytype in self._iter_key_annotations():
            key_address = f'{node.name}:{keyname}'

            shift = 2

            logger('key', key_address, shift=shift)

            shift += 1

            logger('expected type', format_type(keytype), shift=shift)

            if hasattr(self, keyname):
                # If the key exists as instance's attribute already, it is because it's been declared
                # with a default value, and the attribute now holds said
                # default value.
                default_value = getattr(self, keyname)

                logger('default value', default_value, shift=shift)
                logger(
                    'default value type',
                    format_type(
                        type(default_value)),
                    shift=shift)

                # Try to read the value stored in fmf node, and honor the
                # default value.
                value = node.get(keyname, default=default_value)

                logger('raw value', value, shift=shift)
                logger(
                    'raw value type', format_type(
                        type(value)), shift=shift)

                # Special case, apply listify() if key is supposed to be a
                # list.
                if default_value == []:
                    value = tmt.utils.listify(value)

            else:
                value = node.get(keyname)

                logger('raw value', value, shift=shift)
                logger(
                    'raw value type', format_type(
                        type(value)), shift=shift)

            logger('value', value, shift=shift)
            logger('value type', format_type(type(value)), shift=shift)

            errors: List[str] = []

            if not check_type(
                logger,
                f'{node.name}:{keyname}',
                shift,
                value,
                keytype,
                    errors):
                raise tmt.utils.SpecificationError(
                    '\n'.join([
                        f'Invalid key under {node.name}:'
                        ] + [
                        f'  * {error}'
                        for error in reversed(errors)
                        ])
                    )

            # TODO: find a way how to attach "post-validation" callbacks for
            # value conversions
            if keyname == 'link':
                value = tmt.base.Link(value)

            logger(f'final value', value, shift=shift)
            logger(
                f'final value type',
                format_type(
                    type(value)),
                shift=shift)

            setattr(self, keyname, value)

            # Apparently pointless, but makes the debugging output more readable.
            # There may be plenty of tests and plans and keys, a bit of spacing
            # can't hurt.
            logger('')

    def __init__(
            self,
            node: fmf.Tree,
            debug_logger: 'BaseLoggerFnType',
            *args: Any,
            **kwargs: Any
            ) -> None:
        super().__init__(*args, **kwargs)

        self._extract_keys(node, debug_logger)
