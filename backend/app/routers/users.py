from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.orm import Session, joinedload
from typing import List, Optional

from app.database import get_db
from app.models.user import User, UserArea
from app.schemas.user import UserCreate, UserUpdate, UserResponse
from app.services.auth_service import hash_password, require_admin, get_current_user
from app.services.audit_service import log_audit

router = APIRouter(prefix="/api/users", tags=["Usuarios"])


def _sync_areas(db: Session, user: User, areas: Optional[List[str]], actor_username: str) -> Optional[tuple]:
    """Reemplaza el conjunto de áreas del usuario por `areas` (None = no
    tocar; lista vacía = quitarlas todas). Sync completo (delete + insert de
    la diferencia) en vez de POST/DELETE por área individual: la UI siempre
    envía la lista completa desde el formulario de edición, así que no hay
    caso de uso real para endpoints granulares por área -- agregarlos sería
    complejidad sin beneficio concreto (YAGNI).

    Devuelve (antes, despues) ordenados para el log de auditoría, calculados
    desde los sets que esta función ya arma -- NO desde user.area_assignments
    después del cambio: esa colección ORM, cargada antes del sync, no se
    refresca sola solo por hacer db.add()/db.delete() directo sobre filas que
    no pasan por el manejador de la colección, así que leerla justo después
    del flush() daría el estado viejo (bug real, encontrado en verificación
    end-to-end: la acción "areas_changed" nunca se registraba)."""
    if areas is None:
        return None
    actuales = {ua.area for ua in user.area_assignments}
    nuevas = set(areas)

    for ua in list(user.area_assignments):
        if ua.area not in nuevas:
            db.delete(ua)
    for area in nuevas - actuales:
        db.add(UserArea(user_id=user.id, area=area, created_by=actor_username))

    return sorted(actuales), sorted(nuevas)


@router.get("/", response_model=List[UserResponse], summary="Listar usuarios (Admin)")
async def list_users(
    db: Session = Depends(get_db),
    _: User = Depends(require_admin),
):
    return (
        db.query(User)
        .options(joinedload(User.area_assignments))
        .order_by(User.username)
        .all()
    )


@router.post("/", response_model=UserResponse, status_code=201, summary="Crear usuario (Admin)")
async def create_user(
    payload: UserCreate,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin),
):
    if db.query(User).filter(User.username == payload.username).first():
        raise HTTPException(status_code=400, detail="El nombre de usuario ya existe")
    if db.query(User).filter(User.email == payload.email).first():
        raise HTTPException(status_code=400, detail="El correo ya está registrado")

    role = str(payload.role or "readonly")
    user = User(
        username=payload.username,
        email=payload.email or "",
        full_name=payload.full_name or "",
        role=role,
        is_active=payload.is_active,
        hashed_password=hash_password(payload.password),
    )
    db.add(user)
    db.flush()  # asigna user.id sin cerrar la transacción, para poder crear UserArea ya mismo

    areas = payload.areas or []
    if role != "admin":
        for area in areas:
            db.add(UserArea(user_id=user.id, area=area, created_by=current_user.username))

    db.commit()
    db.refresh(user)

    log_audit(
        db, "user", user.id, "create", current_user.username,
        changes={"username": user.username, "role": role, "areas": areas if role != "admin" else "N/A (admin)"},
        request=request,
    )
    return user


@router.put("/{user_id}", response_model=UserResponse, summary="Actualizar usuario (Admin)")
async def update_user(
    user_id: int,
    payload: UserUpdate,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin),
):
    user = (
        db.query(User)
        .options(joinedload(User.area_assignments))
        .filter(User.id == user_id)
        .first()
    )
    if not user:
        raise HTTPException(status_code=404, detail="Usuario no encontrado")

    cambios: dict = {}
    if payload.email is not None and payload.email != user.email:
        cambios["email"] = {"antes": user.email, "despues": payload.email}
        user.email = payload.email
    if payload.full_name is not None and payload.full_name != user.full_name:
        cambios["full_name"] = {"antes": user.full_name, "despues": payload.full_name}
        user.full_name = payload.full_name
    if payload.role is not None and str(payload.role) != user.role:
        cambios["role"] = {"antes": user.role, "despues": str(payload.role)}
        user.role = str(payload.role)
    if payload.is_active is not None and payload.is_active != user.is_active:
        cambios["is_active"] = {"antes": user.is_active, "despues": payload.is_active}
        user.is_active = payload.is_active
    if payload.password:
        user.hashed_password = hash_password(payload.password)
        cambios["password"] = "cambiada"

    if user.role == "admin":
        # Admin no tiene restricción por área (ver auth_service.get_user_areas):
        # cualquier asignación previa queda huérfana/irrelevante, se limpia.
        diff = _sync_areas(db, user, [], current_user.username)
    else:
        diff = _sync_areas(db, user, payload.areas, current_user.username)
    if diff is not None:
        areas_antes, areas_despues = diff
        if areas_antes != areas_despues:
            cambios["areas"] = {"antes": areas_antes, "despues": areas_despues}

    db.commit()
    db.refresh(user)

    if cambios:
        accion = "areas_changed" if set(cambios.keys()) == {"areas"} else "update"
        log_audit(db, "user", user.id, accion, current_user.username, changes=cambios, request=request)
    return user


@router.delete("/{user_id}", status_code=204, summary="Eliminar usuario (Admin)")
async def delete_user(
    user_id: int,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin),
):
    if user_id == current_user.id:
        raise HTTPException(status_code=400, detail="No puedes eliminar tu propio usuario")
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="Usuario no encontrado")

    username_eliminado = user.username
    db.delete(user)  # cascade="all, delete-orphan" en User.area_assignments borra sus UserArea también
    db.commit()

    log_audit(db, "user", user_id, "delete", current_user.username,
              changes={"username_eliminado": username_eliminado}, request=request)
