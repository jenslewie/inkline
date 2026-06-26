from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class NavItem:
    label: str
    href: str


@dataclass(frozen=True)
class NavView:
    language: str
    items: list[NavItem]
