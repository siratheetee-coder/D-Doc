"""School activities are informational and do not modify school-day or meal records."""
from datetime import datetime
from sqlalchemy import Column,Integer,String,Text,DateTime,Boolean
from app.database import Base

class SchoolEvent(Base):
    __tablename__='school_event'
    id=Column(Integer,primary_key=True)
    year=Column(Integer,nullable=False,index=True)
    title=Column(String(200),nullable=False)
    kind=Column(String(20),nullable=False,default='activity')
    start_at=Column(DateTime,nullable=False,index=True)
    end_at=Column(DateTime,nullable=False)
    all_day=Column(Boolean,nullable=False,default=True)
    audience=Column(String(20),nullable=False,default='school')
    targets_json=Column(Text,nullable=False,default='[]')
    location=Column(String(300),default='')
    organizer=Column(String(200),default='')
    note=Column(Text,default='')
    version=Column(Integer,nullable=False,default=1)
    created_by=Column(Integer,nullable=True)
    created_at=Column(DateTime,default=datetime.now)
