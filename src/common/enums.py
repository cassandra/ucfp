"""
General-purpose enumerations reusable across projects. Each is a LabeledEnum
(see common/labeled_enum.py) so it carries a human-readable label/description
and integrates with LabeledEnumField for storage.
"""
from common.labeled_enum import LabeledEnum


class Platform(LabeledEnum):
    """Client / device platform, e.g. for reporting the origin of an API client."""

    UNKNOWN    = ( 'Unknown'   , '' )
    ANDROID    = ( 'Android'   , '' )
    IOS        = ( 'iOS'       , '' )
    LINUX      = ( 'GNU/Linux' , '' )
    MACOS      = ( 'MacOS'     , '' )
    WINDOWS    = ( 'Windows'   , '' )
    OTHER      = ( 'Other'     , '' )

    @classmethod
    def default(cls):
        return cls.UNKNOWN

    @property
    def is_mobile(self):
        return self in [ Platform.ANDROID, Platform.IOS ]

    @property
    def is_ios(self):
        return bool( self == Platform.IOS )

    @property
    def is_android(self):
        return bool( self == Platform.ANDROID )
