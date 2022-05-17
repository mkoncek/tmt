""" (Hopefully) simple module for leveling the playfield of types whose support varies across Python versions. """

import sys

#
# The following are avalable from `typing` module since Python 3.8
#
if sys.version_info.minor >= 8:
    from typing import Literal, TypedDict, final

else:
    from typing_extensions import Literal  # type: ignore[misc]
    from typing_extensions import final  # type: ignore[misc]
    from typing_extensions import TypedDict
