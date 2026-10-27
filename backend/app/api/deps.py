"""FastAPI dependencies shared by the routes."""

from typing import Annotated

from fastapi import Depends, Request

from app.state import AppState


def get_state(request: Request) -> AppState:
    """The `AppState` stored on the application by the lifespan."""
    return request.app.state.app_state


StateDep = Annotated[AppState, Depends(get_state)]
