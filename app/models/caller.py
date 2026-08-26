from sqlalchemy import Column, Integer, String

from app.database.database import Base


class Caller(Base):
    __tablename__ = "call_requests"

    id = Column(Integer, primary_key=True, index=True)

    customer_name = Column(String)
    phone_number = Column(String)
    hotel_name = Column(String)
    check_in_date = Column(String)
    check_out_date = Column(String)
