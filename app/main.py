from urllib import response
from urllib.parse import urlencode
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
    installation_id: int,
    x_api_key: str | None = Header(default=None),
    db: Session = Depends(get_db)
):
    if not x_api_key:
        raise HTTPException(
            status_code=401,
            detail="Missing device API key"
        )

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

    if x_api_key != installation.device_api_key:
        raise HTTPException(
            status_code=401,
            detail="Invalid device API key for this installation"
        )

    return installation
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


def get_user_scope_ids(user):
    """
    Returns the jurisdiction IDs available to the current user.
    Admin users have unrestricted access.
    """

    if user.role == "admin":
        return {
            "province_id": None,
            "district_id": None,
            "substation_id": None
        }

    if user.substation_id is not None:
        return {
            "province_id": None,
            "district_id": None,
            "substation_id": user.substation_id
        }

    if user.district_id is not None:
        return {
            "province_id": None,
            "district_id": user.district_id,
            "substation_id": None
        }

    if user.province_id is not None:
        return {
            "province_id": user.province_id,
            "district_id": None,
            "substation_id": None
        }

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
        status_code=400,
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
    # dependencies=[Depends(verify_device_api_key)]
)
def create_generation_reading(
    installation_id: int,
    reading: GenerationReadingCreate,
    response: Response,
    idempotency_key: str | None = Header(default=None),
    installation = Depends(verify_device_api_key),
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
def get_provinces(
    db: Session = Depends(get_db),
    user = Depends(get_current_user)
):
    scope = get_user_scope_ids(user)

    query = db.query(models.Province)

    if scope["province_id"] is not None:
        query = query.filter(
            models.Province.id == scope["province_id"]
        )

    elif scope["district_id"] is not None:
        query = (
            query
            .join(models.District)
            .filter(
                models.District.id == scope["district_id"]
            )
        )

    elif scope["substation_id"] is not None:
        query = (
            query
            .join(models.District)
            .join(models.GridSubstation)
            .filter(
                models.GridSubstation.id == scope["substation_id"]
            )
        )

    return query.all()

@app.get("/districts")
def get_districts(
    db: Session = Depends(get_db),
    user = Depends(get_current_user)
):
    scope = get_user_scope_ids(user)

    query = db.query(models.District)

    if scope["substation_id"] is not None:
        query = (
            query
            .join(models.GridSubstation)
            .filter(
                models.GridSubstation.id
                == scope["substation_id"]
            )
        )

    elif scope["district_id"] is not None:
        query = query.filter(
            models.District.id
            == scope["district_id"]
        )

    elif scope["province_id"] is not None:
        query = query.filter(
            models.District.province_id
            == scope["province_id"]
        )

    return query.all()
@app.get("/districts/{district_id}")
def get_district(
    district_id: int,
    db: Session = Depends(get_db),
    user = Depends(get_current_user)
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

    # Admin can access any district
    if user.role != "admin":

        # Province-scoped user
        if user.province_id is not None:
            if district.province_id != user.province_id:
                raise HTTPException(
                    status_code=403,
                    detail="Access denied for this district"
                )

        # District-scoped user
        elif user.district_id is not None:
            if district.id != user.district_id:
                raise HTTPException(
                    status_code=403,
                    detail="Access denied for this district"
                )

        # Substation-scoped user
        elif user.substation_id is not None:
            substation = (
                db.query(models.GridSubstation)
                .filter(
                    models.GridSubstation.id
                    == user.substation_id
                )
                .first()
            )

            if substation is None or substation.district_id != district.id:
                raise HTTPException(
                    status_code=403,
                    detail="Access denied for this district"
                )

    return district

@app.get("/provinces/{province_id}/districts")
def get_province_districts(
    province_id: int,
    db: Session = Depends(get_db),
    user = Depends(get_current_user)
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

    # Check whether the user is allowed to access this province
    if user.role != "admin":

        if user.province_id is not None:
            if user.province_id != province_id:
                raise HTTPException(
                    status_code=403,
                    detail="Access denied for this province"
                )

        elif user.district_id is not None:
            district = (
                db.query(models.District)
                .filter(
                    models.District.id == user.district_id
                )
                .first()
            )

            if district is None or district.province_id != province_id:
                raise HTTPException(
                    status_code=403,
                    detail="Access denied for this province"
                )

        elif user.substation_id is not None:
            substation = (
                db.query(models.GridSubstation)
                .filter(
                    models.GridSubstation.id == user.substation_id
                )
                .first()
            )

            if substation is None:
                raise HTTPException(
                    status_code=403,
                    detail="Access denied for this province"
                )

            district = (
                db.query(models.District)
                .filter(
                    models.District.id == substation.district_id
                )
                .first()
            )

            if district is None or district.province_id != province_id:
                raise HTTPException(
                    status_code=403,
                    detail="Access denied for this province"
                )

    districts = (
        db.query(models.District)
        .filter(
            models.District.province_id == province_id
        )
        .all()
    )

    return districts

@app.get("/substations")
def get_substations(
    db: Session = Depends(get_db),
    user = Depends(get_current_user)
):
    scope = get_user_scope_ids(user)

    query = db.query(models.GridSubstation)

    if scope["substation_id"] is not None:
        query = query.filter(
            models.GridSubstation.id
            == scope["substation_id"]
        )

    elif scope["district_id"] is not None:
        query = query.filter(
            models.GridSubstation.district_id
            == scope["district_id"]
        )

    elif scope["province_id"] is not None:
        query = (
            query
            .join(models.District)
            .filter(
                models.District.province_id
                == scope["province_id"]
            )
        )

    return query.all()

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
    db: Session = Depends(get_db),
    user = Depends(get_current_user)
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

    # Check jurisdiction
    if user.role != "admin":

        # Province-scoped user
        if user.province_id is not None:
            if district.province_id != user.province_id:
                raise HTTPException(
                    status_code=403,
                    detail="Access denied for this district"
                )

        # District-scoped user
        elif user.district_id is not None:
            if district.id != user.district_id:
                raise HTTPException(
                    status_code=403,
                    detail="Access denied for this district"
                )

        # Substation-scoped user
        elif user.substation_id is not None:
            substation = (
                db.query(models.GridSubstation)
                .filter(
                    models.GridSubstation.id
                    == user.substation_id
                )
                .first()
            )

            if substation is None:
                raise HTTPException(
                    status_code=403,
                    detail="Access denied for this district"
                )

            if substation.district_id != district.id:
                raise HTTPException(
                    status_code=403,
                    detail="Access denied for this district"
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
def get_installations(
    db: Session = Depends(get_db),
    user = Depends(get_current_user)
):
    scope = get_user_scope_ids(user)

    query = db.query(models.SolarInstallation)

    if scope["substation_id"] is not None:
        query = query.filter(
            models.SolarInstallation.substation_id
            == scope["substation_id"]
        )

    elif scope["district_id"] is not None:
        query = (
            query
            .join(models.GridSubstation)
            .filter(
                models.GridSubstation.district_id
                == scope["district_id"]
            )
        )

    elif scope["province_id"] is not None:
        query = (
            query
            .join(models.GridSubstation)
            .join(models.District)
            .filter(
                models.District.province_id
                == scope["province_id"]
            )
        )

    return query.all()

@app.get("/installations/{installation_id}")
def get_installation(
    installation_id: int,
    response: Response,
    if_none_match: str | None = Header(default=None),
    if_match: str | None = Header(default=None),
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

    etag = f'W/"installation-{installation.id}-{installation.meter_id}"'

    if if_match is not None and if_match != etag:
    raise HTTPException(
        status_code=412,
        detail="If-Match value does not match the current resource"
    )

    if if_none_match == etag:
        return Response(status_code=304, headers={"ETag": etag})        

    response.headers["ETag"] = etag

    return installation
    

@app.get("/substations/{substation_id}/installations")
def get_substation_installations(
    substation_id: int,
    db: Session = Depends(get_db),
    user = Depends(get_current_user)
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

    # Check jurisdiction
    if user.role != "admin":

        # Substation-scoped user
        if user.substation_id is not None:
            if substation.id != user.substation_id:
                raise HTTPException(
                    status_code=403,
                    detail="Access denied for this substation"
                )

        # District-scoped user
        elif user.district_id is not None:
            if substation.district_id != user.district_id:
                raise HTTPException(
                    status_code=403,
                    detail="Access denied for this substation"
                )

        # Province-scoped user
        elif user.province_id is not None:
            district = (
                db.query(models.District)
                .filter(
                    models.District.id
                    == substation.district_id
                )
                .first()
            )

            if district is None or district.province_id != user.province_id:
                raise HTTPException(
                    status_code=403,
                    detail="Access denied for this substation"
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

    # Join related tables only once when jurisdiction filters are used
    if substation_id or district_id or province_id:
        query = query.join(
            models.SolarInstallation,
            models.GenerationReading.installation_id
            == models.SolarInstallation.id
        )

        if district_id or province_id:
            query = query.join(
                models.GridSubstation,
                models.SolarInstallation.substation_id
                == models.GridSubstation.id
            )

        if province_id:
            query = query.join(
                models.District,
                models.GridSubstation.district_id
                == models.District.id
            )

    # Substation filtering
    if substation_id:
        query = query.filter(
            models.SolarInstallation.substation_id == substation_id
        )

    # District filtering
    if district_id:
        query = query.filter(
            models.GridSubstation.district_id == district_id
        )

    # Province filtering
    if province_id:
        query = query.filter(
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
    base_path = f"/installations/{installation_id}/readings"

    query_params = {
        "page_size": page_size,
        "sort": sort
    }

    if start_time:
        query_params["start_time"] = start_time.isoformat()

    if end_time:
        query_params["end_time"] = end_time.isoformat()

    if substation_id is not None:
        query_params["substation_id"] = substation_id

    if district_id is not None:
        query_params["district_id"] = district_id

    if province_id is not None:
        query_params["province_id"] = province_id

    next_page = None
    previous_page = None

    if offset + page_size < total:
        next_params = query_params.copy()
        next_params["page"] = page + 1
        next_page = f"{base_path}?{urlencode(next_params)}"

    if page > 1:
        previous_params = query_params.copy()
        previous_params["page"] = page - 1
        previous_page = f"{base_path}?{urlencode(previous_params)}"

    return {
        "readings": readings,
        "total": total,
        "page": page,
        "page_size": page_size,
        "next_page": next_page,
        "previous_page": previous_page,
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

@app.get("/installations/{installation_id}/readings/{reading_id}")
def get_reading(
    installation_id: int,
    reading_id: int,
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

    reading = (
        db.query(models.GenerationReading)
        .filter(
            models.GenerationReading.id == reading_id,
            models.GenerationReading.installation_id == installation_id
        )
        .first()
    )

    if reading is None:
        raise HTTPException(
            status_code=404,
            detail="Generation reading not found"
        )

    return reading

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

@app.get("/districts/{district_id}/summary")
def get_district_summary(
    district_id: int,
    db: Session = Depends(get_db),
    user = Depends(get_current_user)
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

    # Check jurisdiction access
    if user.role != "admin":

        if user.province_id is not None:
            if district.province_id != user.province_id:
                raise HTTPException(
                    status_code=403,
                    detail="User is not authorized to access this district"
                )

        if user.district_id is not None:
            if district.id != user.district_id:
                raise HTTPException(
                    status_code=403,
                    detail="User is not authorized to access this district"
                )

        # A substation user cannot access the whole district
        if user.substation_id is not None:
            raise HTTPException(
                status_code=403,
                detail="Substation users cannot access district-wide summaries"
            )

    installations = (
        db.query(models.SolarInstallation)
        .join(
            models.GridSubstation,
            models.SolarInstallation.substation_id
            == models.GridSubstation.id
        )
        .filter(
            models.GridSubstation.district_id == district_id
        )
        .all()
    )

    total_capacity_kw = sum(
        installation.capacity_kw
        for installation in installations
    )

    total_current_power_kw = 0
    total_cumulative_energy_kwh = 0

    for installation in installations:

        latest_reading = (
            db.query(models.GenerationReading)
            .filter(
                models.GenerationReading.installation_id
                == installation.id
            )
            .order_by(
                models.GenerationReading.timestamp.desc()
            )
            .first()
        )

        if latest_reading:
            total_current_power_kw += latest_reading.power_kw
            total_cumulative_energy_kwh += (
                latest_reading.cumulative_energy_kwh
            )

    return {
        "district": {
            "id": district.id,
            "name": district.name
        },
        "summary": {
            "total_installations": len(installations),
            "total_capacity_kw": round(total_capacity_kw, 3),
            "current_power_kw": round(total_current_power_kw, 3),
            "cumulative_energy_kwh": round(
                total_cumulative_energy_kwh, 3
            )
        }
    }