"""Task-local matching gaps; completed, filtered and disabled rows are never rerun."""
from sqlalchemy import and_, func
from sqlalchemy.orm import Session, aliased

from app.models.schemas import (
    CleanDuplicateRecord, CleanedDataRecord, CleanJobItemRecord, FilteredItem, MatchResult, MatchTransferLog,
)


def transferred_out_items(db: Session):
    """A departure remains intentional until a later transfer returns to that job."""
    departed, returned = aliased(MatchTransferLog), aliased(MatchTransferLog)
    has_returned = db.query(returned.id).filter(
        returned.raw_data_id == departed.raw_data_id,
        returned.to_clean_job_id == departed.from_clean_job_id,
        returned.id > departed.id,
    ).exists()
    return db.query(
        departed.from_clean_job_id.label('job_id'), departed.raw_data_id.label('raw_data_id'),
        func.max(departed.transferred_at).label('transferred_at'),
    ).filter(
        departed.from_clean_job_id != departed.to_clean_job_id, ~has_returned,
    ).group_by(departed.from_clean_job_id, departed.raw_data_id).subquery()


def missing_match_raw_ids(db: Session, job_id: int):
    """Only cleaned snapshot rows without *any* match result are repairable.

    Disabled results, transfers, active filters and recorded duplicates are intentional.
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
    transferred = transferred_out_items(db)
    return db.query(CleanedDataRecord.raw_data_id).join(
        CleanJobItemRecord, and_(
            CleanJobItemRecord.clean_job_id == job_id,
            CleanJobItemRecord.raw_data_id == CleanedDataRecord.raw_data_id,
        ),
    ).outerjoin(transferred, and_(
        transferred.c.job_id == job_id, transferred.c.raw_data_id == CleanedDataRecord.raw_data_id,
    )).filter(
        CleanedDataRecord.clean_job_id == job_id,
        ~result_exists, ~filtered, ~duplicated, transferred.c.raw_data_id.is_(None),
    ).distinct()
