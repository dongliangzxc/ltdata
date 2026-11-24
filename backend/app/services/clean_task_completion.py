"""Task-local matching gaps; completed, filtered and disabled rows are never rerun."""
from sqlalchemy import and_
from sqlalchemy.orm import Session

from app.models.schemas import (
    CleanDuplicateRecord, CleanedDataRecord, CleanJobItemRecord, FilteredItem, MatchResult,
)


def missing_match_raw_ids(db: Session, job_id: int):
    """Only cleaned snapshot rows without *any* match result are repairable.

    Disabled results, active filters and recorded duplicates are intentional.
    A snapshot with no cleaned output may be a historical unrecorded duplicate,
    so it must not be silently restored by this operation.
    """
    result_exists = db.query(MatchResult.id).filter(
        MatchResult.clean_job_id == job_id,
        MatchResult.raw_data_id == CleanedDataRecord.raw_data_id,
    ).exists()
    filtered = db.query(FilteredItem.id).filter(
        FilteredItem.clean_job_id == job_id,
        FilteredItem.raw_data_id == CleanedDataRecord.raw_data_id,
        FilteredItem.is_recovered == 0,
    ).exists()
    duplicated = db.query(CleanDuplicateRecord.id).filter(
        CleanDuplicateRecord.clean_job_id == job_id,
        CleanDuplicateRecord.raw_data_id == CleanedDataRecord.raw_data_id,
    ).exists()
    return db.query(CleanedDataRecord.raw_data_id).join(
        CleanJobItemRecord, and_(
            CleanJobItemRecord.clean_job_id == job_id,
            CleanJobItemRecord.raw_data_id == CleanedDataRecord.raw_data_id,
        ),
    ).filter(
        CleanedDataRecord.clean_job_id == job_id,
        ~result_exists, ~filtered, ~duplicated,
    ).distinct()
