"""
Core for "loading" keys froma container into object attributes.

This is a common functionality used by both core classes and plugins.
Implementation below provides means for transparent extraction of keys
and values, and optional normalization of input data values to suit code
expectations.

Note: code loading keys from their containers IS NOT validating the values.
Validation is a separate step, performed before key loading.
"""

from typing import (TYPE_CHECKING, Any, Dict, Generator, List, Optional, Tuple,
                    TypeVar, Union)

import fmf

if TYPE_CHECKING:
    from tmt.utils import BaseLoggerFnType, EnvironmentType

from tmt._typing import final

T = TypeVar('T')

# A type representing compatible sources of keys and values.
KeySource = Union[Dict[str, Any], fmf.Tree]


class LoadKeys:
    """ Mixin adding support for Fmf-backed keys with declared types. """

    KEYS_SHOW_ORDER: List[str] = []

    # NOTE: these could be static methods, self is probably useless, but that would
    # cause complications when classes assign them to their members. That makes them
    # no longer static as far as class is concerned, which means they get called with
    # `self` as the first argument. A workaround would be to assign staticmethod()-ized
    # version of them, but that's too much repetition.
    def _normalize_string_list(
            self, value: Union[None, str, List[str]]) -> List[str]:
        if value is None:
            return []

        return [value] if isinstance(value, str) else value

    def _normalize_environment(
            self, value: Optional[Dict[str, Any]]) -> 'EnvironmentType':
        if value is None:
            return {}

        return {
            name: str(value) for name, value in value.items()
            }

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

    def _load_keys(
            self,
            key_source: KeySource,
            logger: 'BaseLoggerFnType') -> None:
        """ Extract values for class-level attributes, and verify they match declared types. """

        # Some sources, like Fmf nodes, may have a name. That may be handy for logging,
        # but since the functionality would be happy with any dict-like object and a name
        # just a nice-to-have additiona, let's make it optional.

        key_source_prefix = f'{getattr(key_source, "name", "")}:'

        for keyname, keytype in self._iter_key_annotations():
            key_address = f'{key_source_prefix}{keyname}'

            shift = 2

            logger('key', key_address, shift=shift)

            shift += 1

            logger('expected type', str(keytype), shift=shift)

            value: Any = None

            if hasattr(self, keyname):
                # If the key exists as instance's attribute already, it is because it's been declared
                # with a default value, and the attribute now holds said
                # default value.
                default_value = getattr(self, keyname)

                logger('default value', default_value, shift=shift)
                logger(
                    'default value type',
                    str(type(default_value)),
                    shift=shift)

                # try+except seems to work better than get(), especially when
                # semantic of fmf.Tree.get() is slightly different than that
                # of dict().get().
                try:
                    value = key_source[keyname]

                except KeyError:
                    value = default_value

                logger('raw value', value, shift=shift)
                logger(
                    'raw value type', str(type(value)), shift=shift)

            else:
                value = key_source.get(keyname)

                logger('raw value', value, shift=shift)
                logger(
                    'raw value type', str(type(value)), shift=shift)

            logger('value', value, shift=shift)
            logger('value type', str(type(value)), shift=shift)

            # TODO: hic sunt coercion
            normalize_callback = getattr(self, f'_normalize_{keyname}', None)

            if normalize_callback:
                value = normalize_callback(value)

                logger('normalized value', value, shift=shift)
                logger('normalized value type', str(type(value)), shift=shift)

            logger(f'final value', value, shift=shift)
            logger(
                f'final value type',
                str(type(value)),
                shift=shift)

            setattr(self, keyname, value)

            # Apparently pointless, but makes the debugging output more readable.
            # There may be plenty of tests and plans and keys, a bit of spacing
            # can't hurt.
            logger('')

    def __init__(
            self,
            key_source: KeySource,
            debug_logger: 'BaseLoggerFnType',
            *args: Any,
            **kwargs: Any
            ) -> None:
        super().__init__(*args, **kwargs)

        self._load_keys(key_source, debug_logger)


#
# One of the possible way how to include validation:
#
#  class ValidateKeys:
#    def _validate_keys(self, key_source: KeySource, logger: 'BaseLoggerFnType') -> None:
#      schema = load_json_schema(f'some/schema/directory/{self.__class__.__name__}')
#
#      if hasattr(key_source, 'whatever_fmf_method_we_get_for_validation'):
#        key_source.whatever_fmf_method_we_get_for_validation(schema)
#
#    def __init__(self, key_source, debug_logger, *args, **kwargs) -> None:
#      super().__init__(key_source, debug_logger, *args, **kwargs)
#
#      self._validate_keys()
#
#
#  class Core(ValidateKeys, LoadKeys, tmt.utils.Common):
#      ...
#
# And all derived classes (Test, Plan, ...) would gain validation out of the box.
#
# Or it could be built into LoadKeys class, but e.g. tmt.steps.provision.Guest
# class does load keys from a dictionary, but seems to need no validation as
# those keys are stored by the class itself, therefore validation seems to be
# optional.
#
