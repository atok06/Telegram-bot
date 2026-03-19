from telegram import InlineKeyboardButton, InlineKeyboardMarkup


def build_ocr_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([[
        InlineKeyboardButton("Русский", callback_data="setlang|rus|ru"),
        InlineKeyboardButton("English", callback_data="setlang|eng|en"),
        InlineKeyboardButton("Turkce", callback_data="setlang|tur|tr"),
    ]])


def build_translate_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([[
        InlineKeyboardButton("Да", callback_data="translate_yes"),
        InlineKeyboardButton("Нет", callback_data="translate_no"),
    ]])


def build_translation_lang_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([[
        InlineKeyboardButton("Русский", callback_data="lang|ru"),
        InlineKeyboardButton("English", callback_data="lang|en"),
        InlineKeyboardButton("Turkce", callback_data="lang|tr"),
    ]])
