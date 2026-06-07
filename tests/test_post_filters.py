# -*- coding: utf-8 -*-

from vk.api import post_passes_filters


def test_ad_stopper_blocks_obvious_commercial_post_even_when_auto_filters_disabled():
    profile = {
        "filters": {
            "enable_auto_filters": False,
            "ad_stopper_enabled": True,
        }
    }

    assert not post_passes_filters("Скидка 50%, купить сейчас, доставка по городу", profile)


def test_ad_stopper_can_be_disabled_for_profile():
    profile = {
        "filters": {
            "enable_auto_filters": False,
            "ad_stopper_enabled": False,
        }
    }

    assert post_passes_filters("Скидка 50%, купить сейчас, доставка по городу", profile)


def test_ad_stopper_uses_profile_keywords():
    profile = {
        "filters": {
            "enable_auto_filters": False,
            "ad_stopper_enabled": True,
            "ad_stop_keywords": ["проверить"],
        }
    }

    assert not post_passes_filters("Проверить цену можно в личных сообщениях", profile)


def test_manual_block_keywords_still_require_auto_filters_enabled():
    disabled_profile = {
        "filters": {
            "enable_auto_filters": False,
            "ad_stopper_enabled": False,
            "block_keywords": ["бан"],
        }
    }
    enabled_profile = {
        "filters": {
            "enable_auto_filters": True,
            "ad_stopper_enabled": False,
            "block_keywords": ["бан"],
        }
    }

    assert post_passes_filters("Обычный текст со словом бан", disabled_profile)
    assert not post_passes_filters("Обычный текст со словом бан", enabled_profile)
