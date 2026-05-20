"""Badges - Badges/gamification module for Oceans of NYC."""

from badges.definitions import BADGE_DEFINITIONS, BadgeDefinition
from badges.evaluator import evaluate_badges_for_contributor

__all__ = ["BADGE_DEFINITIONS", "BadgeDefinition", "evaluate_badges_for_contributor"]
