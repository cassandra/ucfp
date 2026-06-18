"""Enumerations for the US federal tax engine."""
from common.labeled_enum import LabeledEnum


class FilingStatus( LabeledEnum ):
    """Federal income-tax filing status. Married-separate and head-of-household are
    added when a use case needs them."""

    MARRIED_JOINT = ( 'Married Filing Jointly' , 'A married couple filing one joint return.' )
    SINGLE        = ( 'Single'                 , 'An unmarried individual filing alone.' )
