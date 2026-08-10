from sqlalchemy import Column, Integer, String

from src.database import Base


class Client(Base):
    __tablename__ = "clients"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(255), nullable=False)
    contact_email = Column(String(255))
    contact_phone = Column(String(50))
    api_limit = Column(Integer, default=100)


class Caller(Base):
    __tablename__ = "call_requests"

    id = Column(Integer, primary_key=True, index=True)
    customer_name = Column(String)
    phone_number = Column(String)
    hotel_name = Column(String)
    check_in_date = Column(String)
    check_out_date = Column(String)
