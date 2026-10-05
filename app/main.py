from urllib import response
from fastapi import FastAPI, Depends, HTTPException, Query, Response, Header, Request
from fastapi.responses import JSONResponse
from fastapi.exceptions import RequestValidationError
from pydantic import BaseModel
from sqlalchemy.orm import Session
from sqlalchemy.orm import sessionmaker
from datetime import datetime
from .database import Base, engine, get_db, SessionLocal
from . import models

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

Base.metadata.create_all(bind=engine)

from .seed import seed_database

with SessionLocal() as db:
    if db.query(models.Province).count() == 0:
        seed_database()
class GenerationReadingCreate(BaseModel):
    timestamp: datetime
    power_kw: float
    cumulative_energy_kwh: float
    voltage: float

def verify_device_api_key(
    x_api_key: str | None = Header(default=None)
):
    if x_api_key != "solar-device-key-123":
        raise HTTPException(
            status_code=401,
            detail="Invalid or missing device API key"
        )

    return x_api_key
def get_current_user(
    x_user: str | None = Header(default=None),
    db: Session = Depends(get_db)
):
    if not x_user:
        raise HTTPException(
            status_code=401,
            detail="Missing user identity"
        )

    user = (
        db.query(models.User)
        .filter(models.User.username == x_user)
        .first()
    )

    if user is None:
        raise HTTPException(
            status_code=401,
            detail="Invalid user"
        )

    return user
def check_user_scope(user, installation):
    if user.role == "admin":
        return

    substation = installation.substation
    district = substation.district
    province = district.province

    # Province-level access
    if user.province_id is not None:
        if province.id != user.province_id:
            raise HTTPException(
                status_code=403,
                detail="User is not authorized to access this province"
            )

    # District-level access
    if user.district_id is not None:
        if district.id != user.district_id:
            raise HTTPException(
                status_code=403,
                detail="User is not authorized to access this district"
            )

    # Substation-level access
    if user.substation_id is not None:
        if substation.id != user.substation_id:
            raise HTTPException(
                status_code=403,
                detail="User is not authorized to access this substation"
            )

    # No jurisdiction assigned
    if (
        user.province_id is None
        and user.district_id is None
        and user.substation_id is None
    ):
        raise HTTPException(
            status_code=403,
            detail="User has no assigned jurisdiction"
        )

app = FastAPI(title="SLSEA Solar API")

@app.exception_handler(HTTPException)
async def http_exception_handler(
    request: Request,
    exc: HTTPException
):
    error_codes = {
        400: "BAD_REQUEST",
        401: "UNAUTHORIZED",
        403: "FORBIDDEN",
        404: "NOT_FOUND",
        405: "METHOD_NOT_ALLOWED",
        409: "CONFLICT",
        422: "UNPROCESSABLE_ENTITY",
        500: "INTERNAL_SERVER_ERROR"
    }

    code = error_codes.get(
        exc.status_code,
        "HTTP_ERROR"
    )

    return JSONResponse(
        status_code=exc.status_code,
        content={
            "code": code,
            "message": str(exc.detail),
            "detail": "The request could not be completed."
        }
    )

@app.exception_handler(RequestValidationError)
async def validation_exception_handler(
    request: Request,
    exc: RequestValidationError
):
    return JSONResponse(
        status_code=422,
        content={
            "code": "VALIDATION_ERROR",
            "message": "Request validation failed.",
            "detail": exc.errors()
        }
    )

@app.get("/")
def home():
    return {
        "message": "SLSEA Solar API is running"
    }

@app.post(
    "/installations/{installation_id}/readings",
    status_code=201,
    dependencies=[Depends(verify_device_api_key)]
)
def create_generation_reading(
    installation_id: int,
    reading: GenerationReadingCreate,
    response: Response,
    idempotency_key: str | None = Header(default=None),
    db: Session = Depends(get_db)
):
    installation = (
        db.query(models.SolarInstallation)
        .filter(models.SolarInstallation.id == installation_id)
        .first()
    )

    if installation is None:
        raise HTTPException(
            status_code=404,
            detail="Solar installation not found"
        )

    if idempotency_key:
        existing_key = (
            db.query(models.IdempotencyKey)
            .filter(
                models.IdempotencyKey.key == idempotency_key
            )
            .first()
        )

        if existing_key:
            response.status_code = 200
            existing_reading = (
                db.query(models.GenerationReading)
                .filter(
                    models.GenerationReading.id ==
                    existing_key.reading_id
                )
                .first()
            )

            response.headers["Location"] = (
                f"/installations/{installation_id}/readings/"
                f"{existing_reading.id}"
            )

            return existing_reading

    new_reading = models.GenerationReading(
        installation_id=installation_id,
        timestamp=reading.timestamp,
        power_kw=reading.power_kw,
        cumulative_energy_kwh=reading.cumulative_energy_kwh,
        voltage=reading.voltage
    )

    db.add(new_reading)
    db.commit()
    db.refresh(new_reading)

    if idempotency_key:
        new_key = models.IdempotencyKey(
            key=idempotency_key,
            reading_id=new_reading.id
        )

        db.add(new_key)
        db.commit()

    response.headers["Location"] = (
    f"/installations/{installation_id}/readings/{new_reading.id}"
)

    return new_reading      

@app.get("/provinces")
def get_provinces(db: Session = Depends(get_db)):
    provinces = db.query(models.Province).all()

    return provinces

@app.get("/districts")
def get_districts(db: Session = Depends(get_db)):
    districts = db.query(models.District).all()

    return districts

@app.get("/districts/{district_id}")
def get_district(
    district_id: int,
    db: Session = Depends(get_db)
):
    district = (
        db.query(models.District)
        .filter(models.District.id == district_id)
        .first()
    )

    if district is None:
        raise HTTPException(
            status_code=404,
            detail="District not found"
        )

    return district

@app.get("/provinces/{province_id}/districts")
def get_province_districts(
    province_id: int,
    db: Session = Depends(get_db)
):
    province = (
        db.query(models.Province)
        .filter(models.Province.id == province_id)
        .first()
    )

    if province is None:
        raise HTTPException(
            status_code=404,
            detail="Province not found"
        )

    districts = (
        db.query(models.District)
        .filter(models.District.province_id == province_id)
        .all()
    )

    return districts

@app.get("/substations")
def get_substations(db: Session = Depends(get_db)):
    substations = db.query(models.GridSubstation).all()

    return substations

@app.get("/substations/{substation_id}")
def get_substation(
    substation_id: int,
    db: Session = Depends(get_db)
):
    substation = (
        db.query(models.GridSubstation)
        .filter(models.GridSubstation.id == substation_id)
        .first()
    )

    if substation is None:
        raise HTTPException(
            status_code=404,
            detail="Grid substation not found"
        )

    return substation

@app.get("/districts/{district_id}/substations")
def get_district_substations(
    district_id: int,
    db: Session = Depends(get_db)
):
    district = (
        db.query(models.District)
        .filter(models.District.id == district_id)
        .first()
    )

    if district is None:
        raise HTTPException(
            status_code=404,
            detail="District not found"
        )

    substations = (
        db.query(models.GridSubstation)
        .filter(
            models.GridSubstation.district_id == district_id
        )
        .all()
    )

    return substations

@app.get("/installations")
def get_installations(db: Session = Depends(get_db)):
    installations = (
        db.query(models.SolarInstallation)
        .all()
    )

    return installations

@app.get("/installations/{installation_id}")
def get_installation(
    installation_id: int,
    response: Response,
    if_none_match: str | None = Header(default=None),
    db: Session = Depends(get_db),
    user = Depends(get_current_user)
):
    installation = (
        db.query(models.SolarInstallation)
        .filter(
            models.SolarInstallation.id == installation_id
        )
        .first()
    )

    if installation is None:
        raise HTTPException(
            status_code=404,
            detail="Solar installation not found"
        )
        check_user_scope(user, installation)

    etag = f'"installation-{installation.id}-{installation.meter_id}"'

    if if_none_match == etag:
        response.status_code = 304
    return Response(status_code=304)

    response.headers["ETag"] = etag

    return installation

@app.get("/substations/{substation_id}/installations")
def get_substation_installations(
    substation_id: int,
    db: Session = Depends(get_db)
):
    substation = (
        db.query(models.GridSubstation)
        .filter(
            models.GridSubstation.id == substation_id
        )
        .first()
    )

    if substation is None:
        raise HTTPException(
            status_code=404,
            detail="Grid substation not found"
        )

    installations = (
        db.query(models.SolarInstallation)
        .filter(
            models.SolarInstallation.substation_id
            == substation_id
        )
        .all()
    )

    return installations

@app.get("/installations/{installation_id}/readings")
def get_installation_readings(
    installation_id: int,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    start_time: datetime | None = None,
    end_time: datetime | None = None,
    sort: str = Query("asc", pattern="^(asc|desc)$"),
    substation_id: int | None = None,
    district_id: int | None = None,
    province_id: int | None = None,
    db: Session = Depends(get_db),
    user = Depends(get_current_user)
):
    installation = (
        db.query(models.SolarInstallation)
        .filter(
            models.SolarInstallation.id == installation_id
        )
        .first()
    )

    if installation is None:
        raise HTTPException(
            status_code=404,
            detail="Solar installation not found"
        )

    # Check whether the user is allowed to access this installation
    check_user_scope(user, installation)

    query = (
        db.query(models.GenerationReading)
        .filter(
            models.GenerationReading.installation_id == installation_id
        )
    )

    # Time filtering
    if start_time:
        query = query.filter(
            models.GenerationReading.timestamp >= start_time
        )

    if end_time:
        query = query.filter(
            models.GenerationReading.timestamp <= end_time
        )

    # Substation filtering
    if substation_id:
        query = query.join(
            models.SolarInstallation
        ).filter(
            models.SolarInstallation.substation_id == substation_id
        )

    # District filtering
    if district_id:
        query = query.join(
            models.SolarInstallation,
            models.GenerationReading.installation_id
            == models.SolarInstallation.id
        ).join(
            models.GridSubstation,
            models.SolarInstallation.substation_id
            == models.GridSubstation.id
        ).filter(
            models.GridSubstation.district_id == district_id
        )

    # Province filtering
    if province_id:
        query = query.join(
            models.SolarInstallation,
            models.GenerationReading.installation_id
            == models.SolarInstallation.id
        ).join(
            models.GridSubstation,
            models.SolarInstallation.substation_id
            == models.GridSubstation.id
        ).join(
            models.District,
            models.GridSubstation.district_id
            == models.District.id
        ).filter(
            models.District.province_id == province_id
        )

    # Sorting
    if sort == "desc":
        query = query.order_by(
            models.GenerationReading.timestamp.desc()
        )
    else:
        query = query.order_by(
            models.GenerationReading.timestamp.asc()
        )

    # Total number of matching readings
    total = query.count()

    # Pagination
    offset = (page - 1) * page_size

    readings = (
        query
        .offset(offset)
        .limit(page_size)
        .all()
    )

    # Pagination links
    next_page = None
    previous_page = None

    if offset + page_size < total:
        next_page = (
            f"/installations/{installation_id}/readings"
            f"?page={page + 1}&page_size={page_size}"
        )

    if page > 1:
        previous_page = (
            f"/installations/{installation_id}/readings"
            f"?page={page - 1}&page_size={page_size}"
        )

    return {
        "data": readings,
        "pagination": {
            "page": page,
            "page_size": page_size,
            "total": total,
            "next": next_page,
            "previous": previous_page
        }
    }

@app.get("/installations/{installation_id}/readings/latest")
def get_latest_reading(
    installation_id: int,
    db: Session = Depends(get_db),
    user = Depends(get_current_user)
):
    installation = (
        db.query(models.SolarInstallation)
        .filter(models.SolarInstallation.id == installation_id)
        .first()
    )

    if installation is None:
        raise HTTPException(
            status_code=404,
            detail="Solar installation not found"
        )

    check_user_scope(user, installation)

    latest_reading = (
        db.query(models.GenerationReading)
        .filter(
            models.GenerationReading.installation_id == installation_id
        )
        .order_by(
            models.GenerationReading.timestamp.desc()
        )
        .first()
    )

    if latest_reading is None:
        raise HTTPException(
            status_code=404,
            detail="No generation readings found"
        )

    return latest_reading

@app.get("/installations/{installation_id}/summary")
def get_installation_summary(
    installation_id: int,
    db: Session = Depends(get_db),
    user = Depends(get_current_user)
):
    installation = (
        db.query(models.SolarInstallation)
        .filter(models.SolarInstallation.id == installation_id)
        .first()
    )

    if installation is None:
        raise HTTPException(
            status_code=404,
            detail="Solar installation not found"
        )

    check_user_scope(user, installation)

    substation = installation.substation
    district = substation.district
    province = district.province

    latest_reading = (
        db.query(models.GenerationReading)
        .filter(
            models.GenerationReading.installation_id == installation_id
        )
        .order_by(
            models.GenerationReading.timestamp.desc()
        )
        .first()
    )

    return {
        "installation": {
            "id": installation.id,
            "meter_id": installation.meter_id,
            "capacity_kw": installation.capacity_kw
        },
        "substation": {
            "id": substation.id,
            "name": substation.name
        },
        "district": {
            "id": district.id,
            "name": district.name
        },
        "province": {
            "id": province.id,
            "name": province.name
        },
        "latest_reading": latest_reading
    }


    query = (
        db.query(models.GenerationReading)
        .filter(
            models.GenerationReading.installation_id == installation_id
        )
    )

    if start_time:
        query = query.filter(
            models.GenerationReading.timestamp >= start_time
        )

    if end_time:
        query = query.filter(
            models.GenerationReading.timestamp <= end_time
        )
    if substation_id:
        query = query.join(
            models.SolarInstallation
        ).filter(
            models.SolarInstallation.substation_id == substation_id
        )
        if district_id:
            query = query.join(
                models.SolarInstallation,
                models.GenerationReading.installation_id ==
                models.SolarInstallation.id
            ).join(
                models.GridSubstation,
                models.SolarInstallation.substation_id ==
                models.GridSubstation.id
            ).filter(
                models.GridSubstation.district_id == district_id
            )
            if province_id:
                query = query.join(
                    models.SolarInstallation,
                    models.GenerationReading.installation_id ==
                    models.SolarInstallation.id
                ).join(
                    models.GridSubstation,
                    models.SolarInstallation.substation_id ==
                    models.GridSubstation.id
                ).join(
                    models.District,
                    models.GridSubstation.district_id ==
                    models.District.id
                ).filter(
                    models.District.province_id == province_id
                )

    if sort == "desc":
        query = query.order_by(
            models.GenerationReading.timestamp.desc()
        )
    else:
        query = query.order_by(
            models.GenerationReading.timestamp.asc()
        )
    total = query.count()

    offset = (page - 1) * page_size

    readings = (
        query
        .offset(offset)
        .limit(page_size)
        .all()
    )

    next_page = None
    previous_page = None

    if offset + page_size < total:
        next_page = (
            f"/installations/{installation_id}/readings"
            f"?page={page + 1}&page_size={page_size}"
        )

    if page > 1:
        previous_page = (
            f"/installations/{installation_id}/readings"
            f"?page={page - 1}&page_size={page_size}"
        )

    return {
        "data": readings,
        "pagination": {
            "page": page,
            "page_size": page_size,
            "total": total,
            "next": next_page,
            "previous": previous_page
        }
    }