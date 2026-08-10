from sqlalchemy.ext.asyncio import AsyncSession

from app.models.caller import Caller
from app.schemas.caller import CallerRequest


async def save_call(db: AsyncSession, request: CallerRequest) -> Caller:
    caller = Caller(
        customer_name=request.customer_name,
        phone_number=request.phone_number,
        hotel_name=request.hotel_name,
        check_in_date=request.check_in_date,
        check_out_date=request.check_out_date,
    )
    db.add(caller)
    await db.commit()
    await db.refresh(caller)
    return caller
