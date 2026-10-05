from datetime import datetime, timedelta
import math
import random

from sqlalchemy import delete

from .database import Base, SessionLocal, engine
from .models import (
    Province,
    District,
    GridSubstation,
    SolarInstallation,
    GenerationReading,
    User,
)


# ---------------------------------------------------------
# Sri Lankan provinces and districts
# ---------------------------------------------------------

PROVINCES = {
    "Western": [
        "Colombo",
        "Gampaha",
        "Kalutara",
    ],
    "Central": [
        "Kandy",
        "Matale",
        "Nuwara Eliya",
    ],
    "Southern": [
        "Galle",
        "Matara",
        "Hambantota",
    ],
    "Northern": [
        "Jaffna",
        "Kilinochchi",
        "Mannar",
        "Mullaitivu",
        "Vavuniya",
    ],
    "Eastern": [
        "Batticaloa",
        "Ampara",
        "Trincomalee",
    ],
    "North Western": [
        "Kurunegala",
        "Puttalam",
    ],
    "North Central": [
        "Anuradhapura",
        "Polonnaruwa",
    ],
    "Uva": [
        "Badulla",
        "Monaragala",
    ],
    "Sabaragamuwa": [
        "Ratnapura",
        "Kegalle",
    ],
}


# ---------------------------------------------------------
# Main seeding function
# ---------------------------------------------------------

def seed_database():

    db = SessionLocal()

    try:
        print("Clearing existing development data...")

        # Development reset only.
        # This should NOT be used as part of the production API.
        db.execute(delete(GenerationReading))
        db.execute(delete(SolarInstallation))
        db.execute(delete(GridSubstation))
        db.execute(delete(District))
        db.execute(delete(Province))
        db.execute(delete(User))

        db.commit()

        # -------------------------------------------------
        # 1. Provinces
        # -------------------------------------------------

        provinces = {}

        for province_name in PROVINCES:
            province = Province(name=province_name)
            db.add(province)
            provinces[province_name] = province

        db.flush()

        print(f"Created {len(provinces)} provinces.")

        # -------------------------------------------------
        # 2. Districts
        # -------------------------------------------------

        districts = {}

        for province_name, district_names in PROVINCES.items():

            province = provinces[province_name]

            for district_name in district_names:

                district = District(
                    name=district_name,
                    province_id=province.id
                )

                db.add(district)
                districts[district_name] = district

        db.flush()

        print(f"Created {len(districts)} districts.")

        # -------------------------------------------------
        # 3. Grid substations
        # -------------------------------------------------

        substations = []

        district_list = list(districts.values())

        for i in range(20):

            district = district_list[i % len(district_list)]

            substation = GridSubstation(
                name=f"Grid Substation {i + 1:03d}",
                district_id=district.id
            )

            db.add(substation)
            substations.append(substation)

        db.flush()

        print(f"Created {len(substations)} grid substations.")

        # -------------------------------------------------
        # 4. Solar installations
        # -------------------------------------------------

        installations = []

        capacities = [3.0, 5.0, 6.0, 8.0, 10.0, 15.0]

        for i in range(200):

            substation = substations[i % len(substations)]

            installation = SolarInstallation(
                meter_id=f"SLSEA-METER-{i + 1:04d}",
                capacity_kw=random.choice(capacities),
                substation_id=substation.id
            )

            db.add(installation)
            installations.append(installation)

        db.flush()

        print(f"Created {len(installations)} solar installations.")

        # -------------------------------------------------
        # 5. Generation readings
        # -------------------------------------------------

        print("Generating generation readings...")

        readings = []

        # One week
        number_of_days = 7

        # One reading every 15 minutes
        readings_per_day = 96

        start_time = datetime.now().replace(
            hour=0,
            minute=0,
            second=0,
            microsecond=0
        ) - timedelta(days=number_of_days)

        total_readings = 0

        for installation in installations:

            cumulative_energy = 0.0

            for interval in range(number_of_days * readings_per_day):

                timestamp = start_time + timedelta(
                    minutes=15 * interval
                )

                # Convert time into hours
                hour = timestamp.hour + timestamp.minute / 60

                # Solar generation mainly occurs between
                # approximately 6:00 AM and 6:00 PM.
                if 6 <= hour <= 18:

                    # Smooth daytime generation curve
                    daylight_position = (
                        (hour - 6) / 12
                    )

                    solar_factor = math.sin(
                        math.pi * daylight_position
                    )

                    power = (
                        installation.capacity_kw
                        * solar_factor
                        * random.uniform(0.75, 1.0)
                    )

                else:
                    power = 0.0

                # Energy generated during this 15-minute interval
                energy_interval = power * 0.25

                cumulative_energy += energy_interval

                voltage = random.uniform(220, 240)

                reading = GenerationReading(
                    installation_id=installation.id,
                    timestamp=timestamp,
                    power_kw=round(power, 3),
                    cumulative_energy_kwh=round(
                        cumulative_energy,
                        3
                    ),
                    voltage=round(voltage, 2)
                )

                readings.append(reading)
                total_readings += 1

                # Insert in batches to avoid using too much memory
                if len(readings) >= 5000:

                    db.add_all(readings)
                    db.commit()

                    readings.clear()

                    print(
                        f"Inserted {total_readings:,} readings..."
                    )

        # Insert remaining readings
        if readings:
            db.add_all(readings)
            db.commit()

        # -------------------------------------------------
        # 6. Users
        # -------------------------------------------------

        admin = User(
            username="admin",
            role="admin"
        )

        db.add(admin)

        # Province-scoped user
        western_user = User(
            username="western_manager",
            role="province_manager",
            province_id=provinces["Western"].id
        )

        db.add(western_user)

        # District-scoped user
        colombo_user = User(
            username="colombo_manager",
            role="district_manager",
            district_id=districts["Colombo"].id
        )

        db.add(colombo_user)

        db.commit()

        print()
        print("========================================")
        print("DATABASE SEEDING COMPLETED")
        print("========================================")
        print(f"Provinces:      {len(provinces)}")
        print(f"Districts:      {len(districts)}")
        print(f"Substations:    {len(substations)}")
        print(f"Installations:  {len(installations)}")
        print(f"Readings:       {total_readings:,}")
        print("Users:          3")
        print("========================================")

    except Exception:
        db.rollback()
        raise

    finally:
        db.close()


if __name__ == "__main__":
    seed_database()