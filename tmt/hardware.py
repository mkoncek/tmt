# coding: utf-8

"""
Guest hardware requirements specification and helpers.

TMT allows metadata describe various HW requirements a guest needs to satisfy.
This package provides useful functions and classes for core functionality and
shared across provision plugins.

Parsing of HW requirements
==========================

Set of HW requirements, as given by test or plan metadata, is represented by
Python structures - lists, mappings, primitive types - when loaded from fmf
files. Part of the code below converts this representation to a tree of objects
that provide helpful operations for easier evaluation and processing of HW
requirements.

Each HW requirement "rule" in original metadata is a constraint, a condition
the eventual guest HW must satisfy. Each node of the tree created from HW
requirements is therefore called "a constraint", and represents either a single
condition ("trivial" constraints), or a set of such conditions plus a function
reducing their separate outcomes to one final answer for the whole set (think
:py:func:`any` and :py:func:`all` built-in functions) ("compound" constraints).
Components of each constraint - dimension, operator, value, units - are
decoupled from the rest, and made available for inspection.

[1] https://tmt.readthedocs.io/en/latest/spec/plans.html#hardware
"""

import dataclasses
import enum
import functools
import itertools
import operator
import re
from typing import (Any, Callable, Dict, Iterable, Iterator, List, NamedTuple,
                    Optional, Type, TypeVar, Union)

import pint
from pint import Quantity

import tmt.utils

# from . import Failure, SerializableContainer

#: Unit registry, used and shared by all code.
UNITS = pint.UnitRegistry()


# Special type variable, used in `Constraint.from_specification` - we bound this return value to
# always be a subclass
# of `Constraint` class, instead of just any class in general.
T = TypeVar('T', bound='Constraint')


class Operator(enum.Enum):
    """
    Binary operators defined by specification.
    """

    EQ = '=='
    NEQ = '!='
    GT = '>'
    GTE = '>='
    LT = '<'
    LTE = '<='
    MATCH = '=~'
    CONTAINS = 'contains'
    NOTCONTAINS = 'not contains'


# Regular expression to match and split the `value`` part of the key:value pair.
# Said `value` bundles together the operator, the actual value of the constraint,
# and units.
VALUE_PATTERN = re.compile(
    rf'^(?P<operator>{"|".join(operator.value for operator in Operator)})?\s*(?P<value>.+?)\s*$')

# TODO: provide comment
PROPERTY_PATTERN = re.compile(r'(?P<property_name>[a-z_]+)(?:\[(?P<index>[+-]?\d+)\])?')
# TODO: provide comment
PROPERTY_EXPAND_PATTERN = re.compile(
    r'(?P<name>[a-z_+]+)(?:\[(?P<index>[+-]?\d+)\])?(?:\.(?P<child_name>[a-z_]+))?'
)

# Type of the operator callable. The operators accept two arguments, and return
# a boolean evaluation of relationship of their two inputs.
OperatorHandlerType = Callable[[Any, Any], bool]

# Type describing raw requirements as Python lists and mappings.
#
# mypy does not support cyclic definition, it would be much easier to just define this:
#
#   SpecType = Dict[str, Union[int, float, str, 'SpecType', List['SpecType']]]
#
# Instead of resorting to ``Any``, we'll keep the type tracked by giving it its own name.
#
# See https://github.com/python/mypy/issues/731 for details.
SpecType = Any

# TODO: provide comment
ConstraintValueType = Union[int, Quantity, str, bool]
# TODO: provide comment
# Almost like the ConstraintValueType, but this one can be measured and may have units.
MeasurableConstraintValueType = Union[int, Quantity]


class ConstraintNameComponents(NamedTuple):
    """
    Components of a constraint name.
    """

    property: str
    property_index: Optional[int]
    child_property: Optional[str]


def match(text: str, pattern: str) -> bool:
    """
    Match a text against a given regular expression.

    :param text: string to examine.
    :param pattern: regular expression.
    :returns: ``True`` if pattern matches the string.
    """

    return re.match(pattern, text) is not None


def notcontains(haystack: List[str], needle: str) -> bool:
    """
    Find out whether an item is in the given list.

    .. note::

       Opposite of :py:func:`operator.contains`.

    :param haystack: container to examine.
    :param needle: item to look for in ``haystack``.
    :returns: ``True`` if ``needle`` is in ``haystack``.
    """

    return needle not in haystack


OPERATOR_SIGN_TO_OPERATOR = {
    '=': Operator.EQ,
    '==': Operator.EQ,
    '!=': Operator.NEQ,
    '>': Operator.GT,
    '>=': Operator.GTE,
    '<': Operator.LT,
    '<=': Operator.LTE,
    '=~': Operator.MATCH,
    'contains': Operator.CONTAINS,
    'not contains': Operator.NOTCONTAINS
}


OPERATOR_TO_HANDLER: Dict[Operator, OperatorHandlerType] = {
    Operator.EQ: operator.eq,
    Operator.NEQ: operator.ne,
    Operator.GT: operator.gt,
    Operator.GTE: operator.ge,
    Operator.LT: operator.lt,
    Operator.LTE: operator.le,
    Operator.MATCH: match,
    Operator.CONTAINS: operator.contains,
    Operator.NOTCONTAINS: notcontains
}


# TODO: provide comment
ReducerType = Callable[[Iterable[bool]], bool]


class ParseError(tmt.utils.MetadataError):
    """
    Raised when HW requirement parsing fails.
    """

    def __init__(self, constraint_name: str, raw_value: str,
                 message: Optional[str] = None) -> None:
        """
        Raise when HW requirement parsing fails.

        :param constraint_name: name of the constraint that caused issues.
        :param raw_value: original raw value.
        :param message: optional error message.
        """

        super().__init__(message or 'failed to parse a constraint')

        self.constraint_name = constraint_name
        self.raw_value = raw_value


#
# Constraint classes
#

class ConstraintBase(tmt.utils.SerializableContainer):
    """
    Base class for all classes representing one or more constraints.
    """

    def uses_constraint(self, parent: tmt.utils.Common, constraint_name: str) -> bool:
        """
        Inspect constraint whether the constraint or one of its children use a constraint of
        a given name.

        :param logger: logger to use for logging.
        :param constraint_name: constraint name to look for.
        :raises NotImplementedError: method is left for child classes to implement.
        """

        raise NotImplementedError()

    def spans(
            self,
            parent: tmt.utils.Common,
            members: Optional[List['ConstraintBase']] = None
            ) -> Iterator[List['ConstraintBase']]:
        """
        Generate all distinct spans covered by this constraint.

        For a trivial constraint, there is only one span, and that's the constraint itself. In the
        case of compound constraints, the set of spans would be bigger, depending on the
        constraint's ``reducer``.

        :param logger: logger to use for logging.
        :param members: if specified, each span generated by this method is prepended with this
            list.
        :yields: iterator over all spans.
        """

        yield (members or []) + [self]


class CompoundConstraint(ConstraintBase):
    """
    Base class for all *compound* constraints.
    """

    def __init__(
            self,
            reducer: ReducerType = any,
            constraints: Optional[List[ConstraintBase]] = None
            ) -> None:
        """
        Construct a compound constraint, constraint imposed to more than one dimension.

        :param reducer: a callable reducing a list of results from child constraints into the final
            answer.
        :param constraints: child contraints.
        """

        self.reducer = reducer
        self.constraints = constraints or []

    def to_serialized(self) -> Dict[str, Any]:
        """
        Return Python built-in types representing the content of this container.

        See :py:meth:`unserialize` for the reversal operation.

        :returns: serialized form of this constraint.
        """

        return {
            self.__class__.__name__.lower(): [
                constraint.to_serialized() for constraint in self.constraints
                ]
            }

    def uses_constraint(self, parent: tmt.utils.Common, constraint_name: str) -> bool:
        """
        Inspect constraint whether it or its children use a constraint of a given name.

        :param logger: logger to use for logging.
        :param constraint_name: constraint name to look for.
        :returns: ``True`` if the given constraint or its children use given constraint name.
        """

        # Using "any" on purpose: we cannot use the reducer belonging to this constraint,
        # because that one may yield result based on validity of all child constraints.
        # But we want to answer the question "is *any* of child constraints using the given
        # constraint?", not "are all using it?".
        return any(
            constraint.uses_constraint(parent, constraint_name)
            for constraint in self.constraints
            )

    def spans(
            self,
            parent: tmt.utils.Common,
            members: Optional[List[ConstraintBase]] = None
            ) -> Iterator[List[ConstraintBase]]:
        """
        Generate all distinct spans covered by this constraint.

        Since the ``and`` reducer demands all child constraints must be satisfied, and some of
        these constraints can also be compound constraints, we need to construct a cartesian
        product of spans yielded by child constraints to include all possible combinations.

        :param logger: logger to use for logging.
        :param members: if specified, each span generated by this method is prepended with this
            list.
        :raises NotImplementedError: default implementation is left undefined for compound
            constraints.
        """

        raise NotImplementedError()


@dataclasses.dataclass(repr=False)
class Constraint(ConstraintBase):
    """
    A constraint imposing a particular limit to one of the guest properties.
    """

    # Name of the constraint. Used for logging purposes, usually matches the
    # name of the system property.
    name: str

    # A binary operation to use for comparing the constraint value and the
    # value specified by system or flavor.
    operator: Operator

    # A callable comparing the flavor value and the constraint value.
    operator_handler: OperatorHandlerType

    # Constraint value.
    value: ConstraintValueType

    # Stored for possible inspection by more advanced processing.
    raw_value: str

    # If set, it is a raw unit specified by the constraint.
    unit: Optional[str] = None

    # If set, it is a "bigger" constraint, to which this constraint logically
    # belongs as one of its aspects.
    original_constraint: Optional['Constraint'] = None

    @classmethod
    def from_specification(
            cls: Type[T],
            name: str,
            raw_value: str,
            as_quantity: bool = True,
            as_cast: Optional[Callable[[str], ConstraintValueType]] = None,
            original_constraint: Optional['Constraint'] = None
            ) -> T:
        """
        Parse raw constraint specification into our internal representation.

        :param name: name of the constraint.
        :param raw_value: raw value of the constraint.
        :param as_quantity: if set, value is treated as a quantity containing also unit, and as
            such the raw value is converted to :py:class`pint.Quantity` instance.
        :param as_cast: if specified, this callable is used to convert raw value to its final type.
        :param original_constraint: when specified, new constraint logically belongs to
            ``original_constraint``, possibly representing one of its aspects.
        :raises ParseError: when parsing fails.
        :returns: a :py:class:`Constraint` representing the given specification.
        """

        parsed_value = VALUE_PATTERN.match(raw_value)

        if not parsed_value:
            raise ParseError(constraint_name=name, raw_value=raw_value)

        groups = parsed_value.groupdict()

        if groups['operator']:
            operator = OPERATOR_SIGN_TO_OPERATOR[groups['operator']]

        else:
            operator = Operator.EQ

        raw_value = groups['value']

        if as_quantity:
            value = UNITS(raw_value)

        elif as_cast is not None:
            value = as_cast(raw_value)

        else:
            value = raw_value

        return cls(
            name=name,
            operator=operator,
            operator_handler=OPERATOR_TO_HANDLER[operator],
            value=value,
            raw_value=raw_value,
            original_constraint=original_constraint
            )

    def to_serialized(self) -> Dict[str, Any]:
        return {
            'name': self.name,
            'operator': self.operator,
            'value': self.value
            }

    def expand_name(self) -> ConstraintNameComponents:
        """
        Expand constraint name into its components.

        :returns: tuple consisting of constraint name components: name, optional indices, child
        properties, etc.
        """

        match = PROPERTY_EXPAND_PATTERN.match(self.name)

        # Cannot happen as long as we test our pattern well...
        assert match is not None

        groups = match.groupdict()

        return ConstraintNameComponents(
            property=groups['name'],
            property_index=int(groups['index']) if groups['index'] is not None else None,
            child_property=groups['child_name']
            )

    def change_operator(self, operator: Operator) -> None:
        """
        Change operator of this constraint to a given one.

        :param operator: new operator.
        """

        self.operator = operator
        self.operator_handler = OPERATOR_TO_HANDLER[operator]

    def uses_constraint(self, parent: tmt.utils.Common, constraint_name: str) -> bool:
        """
        Inspect constraint whether it or its children use a constraint of a given name.

        :param logger: logger to use for logging.
        :param constraint_name: constraint name to look for.
        :returns: ``True`` if the given constraint or its children use given constraint name.
        """

        return self.expand_name().property == constraint_name


@dataclasses.dataclass(repr=False)
class And(CompoundConstraint):
    """
    Represents constraints that are grouped in ``and`` fashion.
    """

    def __init__(self, constraints: Optional[List[ConstraintBase]] = None) -> None:
        """
        Hold constraints that are grouped in ``and`` fashion.

        :param constraints: list of constraints to group.
        """

        super().__init__(all, constraints=constraints)

    def spans(
            self,
            parent: tmt.utils.Common,
            members: Optional[List[ConstraintBase]] = None
            ) -> Iterator[List[ConstraintBase]]:
        """
        Generate all distinct spans covered by this constraint.

        Since the ``and`` reducer demands all child constraints must be satisfied, and some of
        these constraints can also be compound constraints, we need to construct a cartesian
        product of spans yielded by child constraints to include all possible combinations.

        :param logger: logger to use for logging.
        :param members: if specified, each span generated by this method is prepended with this
            list.
        :yields: all possible spans.
        """

        members = members or []

        # List of non-compound constraints - we just slap these into every combination we generate
        simple_constraints = [
            constraint
            for constraint in self.constraints
            if not isinstance(constraint, CompoundConstraint)
            ]

        # Compound constraints - these we will ask to generate their spans, and we produce
        # cartesian product from the output.
        compound_constraints = [
            constraint
            for constraint in self.constraints
            if isinstance(constraint, CompoundConstraint)
            ]

        for compounds in itertools.product(*[constraint.spans(parent)
                                           for constraint in compound_constraints]):
            # Note that `product` returns an item for each iterable, and those items are lists,
            # because that's what `spans()` returns. Use `sum` to linearize the list of lists.
            yield members + sum(compounds, []) + simple_constraints


@dataclasses.dataclass(repr=False)
class Or(CompoundConstraint):
    """
    Represents constraints that are grouped in ``or`` fashion.
    """

    def __init__(self, constraints: Optional[List[ConstraintBase]] = None) -> None:
        """
        Hold constraints that are grouped in ``or`` fashion.

        :param constraints: list of constraints to group.
        """

        super().__init__(any, constraints=constraints)

    def spans(
            self,
            parent: tmt.utils.Common,
            members: Optional[List[ConstraintBase]] = None
            ) -> Iterator[List[ConstraintBase]]:
        """
        Generate all distinct spans covered by this constraint.

        Since the ``any`` reducer allows any child constraints to be satisfied for the whole group
        to evaluate as ``True``, it is trivial to generate spans - each child constraint shall
        provide its own "branch", and there is no need for products or joins of any kind.

        :param logger: logger to use for logging.
        :param members: if specified, each span generated by this method is prepended with this
            list.
        :yields: all possible spans.
        """

        members = members or []

        for constraint in self.constraints:
            for span in constraint.spans(parent):
                yield members + span


#
# Constraint parsing
#

def ungroupify(fn: Callable[[SpecType], ConstraintBase]) -> Callable[[SpecType], ConstraintBase]:
    @functools.wraps(fn)
    def wrapper(spec: SpecType) -> ConstraintBase:
        constraint = fn(spec)

        if isinstance(constraint, CompoundConstraint) and len(constraint.constraints) == 1:
            return constraint.constraints[0]

        return constraint

    return wrapper


@ungroupify
def _parse_boot(spec: SpecType) -> ConstraintBase:
    """
    Parse a boot-related constraints.

    :param spec: raw constraint block specification.
    :returns: block representation as :py:class:`ConstraintBase` or one of its subclasses.
    """

    group = And()

    if 'method' in spec:
        constraint = Constraint.from_specification(
            'boot.method', spec["method"], as_quantity=False)

        if constraint.operator == Operator.EQ:
            constraint.change_operator(Operator.CONTAINS)

        elif constraint.operator == Operator.NEQ:
            constraint.change_operator(Operator.NOTCONTAINS)

        group.constraints += [constraint]

    return group


@ungroupify
def _parse_virtualization(spec: SpecType) -> ConstraintBase:
    """
    Parse a virtualization-related constraints.

    :param spec: raw constraint block specification.
    :returns: block representation as :py:class:`ConstraintBase` or one of its subclasses.
    """

    group = And()

    if 'is-virtualized' in spec:
        group.constraints += [
            Constraint.from_specification(
                'virtualization.is_virtualized',
                str(spec['is-virtualized']),
                as_quantity=False,
                as_cast=bool
                )
            ]

    if 'is-supported' in spec:
        group.constraints += [
            Constraint.from_specification(
                'virtualization.is_supported',
                str(spec['is-supported']),
                as_quantity=False,
                as_cast=bool
                )
            ]

    if 'hypervisor' in spec:
        group.constraints += [
            Constraint.from_specification(
                'virtualization.hypervisor',
                spec['hypervisor'],
                as_quantity=False
                )
            ]

    return group


@ungroupify
def _parse_cpu(spec: SpecType) -> ConstraintBase:
    """
    Parse a cpu-related constraints.

    :param spec: raw constraint block specification.
    :returns: block representation as :py:class:`ConstraintBase` or one of its subclasses.
    """

    group = And()

    group.constraints += [
        Constraint.from_specification(f'cpu.{constraint_name}', str(spec[constraint_name]))
        for constraint_name in ('processors', 'cores', 'model', 'family')
        if constraint_name in spec
        ]

    group.constraints += [
        Constraint.from_specification(
            f'cpu.{constraint_name.replace("-", "_")}',
            str(spec[constraint_name]),
            as_quantity=False
            )
        for constraint_name in ('model-name',)
        if constraint_name in spec
        ]

    return group


def _parse_disk(spec: SpecType, disk_index: int) -> ConstraintBase:
    """
    Parse a disk-related constraints.

    :param spec: raw constraint block specification.
    :param disk_index: index of this disk among its peers in specification.
    :returns: block representation as :py:class:`ConstraintBase` or one of its subclasses.
    """

    group = And()

    group.constraints += [
        Constraint.from_specification(
            f'disk[{disk_index}].{constraint_name}', str(
                spec[constraint_name])) for constraint_name in (
            'size',) if constraint_name in spec]

    return group


@ungroupify
def _parse_disks(spec: SpecType) -> ConstraintBase:
    """
    Parse a storage-related constraints.

    :param spec: raw constraint block specification.
    :returns: block representation as :py:class:`ConstraintBase` or one of its subclasses.
    """

    # The old-style constraint when `disk` was a mapping. Remove once v0.0.26 is gone.
    if isinstance(spec, dict):
        return _parse_disk(spec, 0)

    group = And()

    group.constraints += [
        _parse_disk(disk_spec, disk_index)
        for disk_index, disk_spec in enumerate(spec)
        ]

    return group


def _parse_network(spec: SpecType, network_index: int) -> ConstraintBase:
    """
    Parse a network-related constraints.

    :param spec: raw constraint block specification.
    :param network_index: index of this network among its peers in specification.
    :returns: block representation as :py:class:`ConstraintBase` or one of its subclasses.
    """

    group = And()

    group.constraints += [
        Constraint.from_specification(
            f'network[{network_index}].{constraint_name}',
            str(spec[constraint_name]),
            as_quantity=False
            )
        for constraint_name in ('type',)
        if constraint_name in spec
        ]

    return group


@ungroupify
def _parse_networks(spec: SpecType) -> ConstraintBase:
    """
    Parse a network-related constraints.

    :param spec: raw constraint block specification.
    :returns: block representation as :py:class:`ConstraintBase` or one of its subclasses.
    """

    group = And()

    group.constraints += [
        _parse_network(network_spec, network_index)
        for network_index, network_spec in enumerate(spec)
        ]

    return group


@ungroupify
def _parse_generic_spec(spec: SpecType) -> ConstraintBase:
    """
    Parse actual constraints.

    :param spec: raw constraint block specification.
    :returns: block representation as :py:class:`ConstraintBase` or one of its subclasses.
    """

    group = And()

    if 'arch' in spec:
        group.constraints += [
            Constraint.from_specification(
                'arch',
                spec['arch'],
                as_quantity=False)]

    if 'boot' in spec:
        group.constraints += [_parse_boot(spec['boot'])]

    if 'cpu' in spec:
        group.constraints += [_parse_cpu(spec['cpu'])]

    if 'memory' in spec:
        group.constraints += [Constraint.from_specification('memory', str(spec['memory']))]

    if 'disk' in spec:
        group.constraints += [_parse_disks(spec['disk'])]

    if 'network' in spec:
        group.constraints += [_parse_networks(spec['network'])]

    if 'hostname' in spec:
        group.constraints += [
            Constraint.from_specification(
                'hostname',
                spec['hostname'],
                as_quantity=False)]

    if 'virtualization' in spec:
        group.constraints += [_parse_virtualization(spec['virtualization'])]

    return group


@ungroupify
def _parse_and(spec: SpecType) -> ConstraintBase:
    """
    Parse an ``and`` clause holding one or more subblocks or constraints.

    :param spec: raw constraint block specification.
    :returns: block representation as :py:class:`ConstraintBase` or one of its subclasses.
    """

    group = And()

    group.constraints += [
        _parse_block(member)
        for member in spec
        ]

    return group


@ungroupify
def _parse_or(spec: SpecType) -> ConstraintBase:
    """
    Parse an ``or`` clause holding one or more subblocks or constraints.

    :param spec: raw constraint block specification.
    :returns: block representation as :py:class:`ConstraintBase` or one of its subclasses.
    """

    group = Or()

    group.constraints += [
        _parse_block(member)
        for member in spec
        ]

    return group


def _parse_block(spec: SpecType) -> ConstraintBase:
    """
    Parse a generic block of HW constraints - may contain ``and`` and ``or``
    subblocks and actual constraints.

    :param spec: raw constraint block specification.
    :returns: block representation as :py:class:`ConstraintBase` or one of its
    subclasses.
    """

    if 'and' in spec:
        return _parse_and(spec['and'])

    elif 'or' in spec:
        return _parse_or(spec['or'])

    else:
        return _parse_generic_spec(spec)


def parse_hw_requirements(spec: SpecType) -> ConstraintBase:
    """
    Convert raw specification of HW constraints to our internal representation.

    :param spec: raw constraints specification as stored in an environment.
    :returns: root of HW constraints tree.
    """

    return _parse_block(spec)
