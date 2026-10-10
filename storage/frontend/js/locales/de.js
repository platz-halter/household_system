// German strings. Informal "du" register throughout, matching
// household_system's own established choice for this household app.
// Keep this file in exact key-parity with en.js; nothing enforces that
// automatically, so add a key's German counterpart in the same edit
// that adds it to en.js.
export const de = {
  // --- common ------------------------------------------------------------
  "common.close": "Schließen",
  "common.cancel": "Abbrechen",
  "common.delete": "Löschen",
  "common.name_required": "Name ist erforderlich",
  "common.added_toast": '„{name}“ hinzugefügt',

  // --- app chrome ------------------------------------------------------
  "app.title": "Household System — Storage",
  "nav.overview": "Übersicht",
  "nav.settings": "Einstellungen",

  // --- confirmDialog.js ----------------------------------------------
  "confirm.default_title": "Bist du sicher?",
  "confirm.default_confirm": "Bestätigen",
  "confirm.default_cancel": "Abbrechen",

  // --- theme.js --------------------------------------------------------
  "theme.light": "Hell",
  "theme.dark": "Dunkel",

  // --- login.js / main.js ------------------------------------------------
  "login.with_authentik": "Mit Authentik anmelden",
  "login.use_local": "Stattdessen ein lokales Konto verwenden",
  "login.use_authentik_instead": "Stattdessen Authentik verwenden",
  "login.username": "Benutzername",
  "login.password": "Passwort",
  "login.submit": "Anmelden",
  "login.submitting": "Anmeldung läuft…",
  "login.authentik_unreachable": "Authentik ist derzeit nicht erreichbar — versuche es mit einem lokalen Konto",
  "login.failed": "Anmeldung fehlgeschlagen",
  "login.authentik_callback_failed": "Anmeldung mit Authentik fehlgeschlagen",

  // --- api.js ----------------------------------------------------------
  "api.network_error": "Netzwerkfehler — ist der Server erreichbar?",
  "api.forbidden": "Du hast keine Berechtigung dafür",
  "api.request_failed": "Anfrage fehlgeschlagen",
  "api.session_expired": "Sitzung abgelaufen",

  // --- settings.js -------------------------------------------------------
  "settings.account": "Konto",
  "settings.unknown_user": "Unbekannter Benutzer",
  "settings.unknown_role": "unbekannte Rolle",
  "settings.role_admin": "Admin",
  "settings.role_user": "Nutzer",
  "settings.role_viewer": "Betrachter",
  "settings.source_local": "Lokal",
  "settings.source_authentik": "Authentik",
  "settings.storage_heading": "Lager",
  "settings.manage_rooms": "Räume verwalten",
  "settings.theme": "Darstellung",
  "settings.language": "Sprache",
  "settings.language_desc": "Gilt nur auf diesem Gerät",
  "settings.logout": "Abmelden",
  "settings.version": "Storage v{version}",
  "settings.logout_confirm_title": "Abmelden",
  "settings.logout_confirm_message": "Möchtest du dich wirklich abmelden?",

  // --- rooms.js -----------------------------------------------------------
  "rooms.heading": "Räume",
  "rooms.desc":
    "Die Räume, die beim Festlegen des Standorts eines Gegenstands zur Auswahl stehen — füge hier einen hinzu, bevor du ihn bei einem Gegenstand verwendest, statt jedes Mal einen neuen zu tippen.",
  "rooms.new_room_placeholder": "Neuer Raumname",
  "rooms.add_btn": "Hinzufügen",
  "rooms.enter_name_warning": "Gib einen Raumnamen ein",
  "rooms.couldnt_load": "Räume konnten nicht geladen werden",
  "rooms.no_rooms_yet": "Noch keine Räume",
  "rooms.delete_aria": "{name} löschen",
  "rooms.delete_title": "Raum löschen",
  "rooms.delete_message": '„{name}“ löschen? Das funktioniert nur, solange dort kein Gegenstand gelagert ist.',
  "rooms.deleted_toast": "Raum gelöscht",

  // --- overview.js ----------------------------------------------------------
  "overview.search_placeholder": "Gegenstände durchsuchen…",
  "overview.filter_btn": "Filter",
  "overview.select_items_aria": "Gegenstände auswählen",
  "overview.sort_name_asc": "Name (A–Z)",
  "overview.sort_name_desc": "Name (Z–A)",
  "overview.sort_qty_asc": "Menge (niedrig–hoch)",
  "overview.sort_qty_desc": "Menge (hoch–niedrig)",
  "overview.sort_updated": "Zuletzt aktualisiert",
  "overview.sort_created": "Neueste zuerst",
  "overview.room_label": "Raum",
  "overview.any": "Alle",
  "overview.quantity_label": "Menge",
  "overview.min_placeholder": "Min",
  "overview.max_placeholder": "Max",
  "overview.shelf_label": "Regal",
  "overview.level_label": "Ebene",
  "overview.clear_filters_btn": "Filter zurücksetzen",
  "overview.page_label": "Seite {current} von {total}",
  "overview.no_items_found": "Keine Gegenstände gefunden",
  "overview.couldnt_load_items": "Gegenstände konnten nicht geladen werden. Zum erneuten Versuch nach unten ziehen.",
  "overview.add_item_aria": "Gegenstand hinzufügen",
  "overview.uncountable": "unzählbar",
  "overview.selected_count": "{n} ausgewählt",
  "overview.cancel_selection_aria": "Auswahl abbrechen",
  "overview.bulk_edit_btn": "Bearbeiten",
  "overview.delete_items_title": "Gegenstände löschen",
  "overview.delete_items_message": {
    one: "{n} Gegenstand löschen? Das kann nicht rückgängig gemacht werden.",
    other: "{n} Gegenstände löschen? Das kann nicht rückgängig gemacht werden.",
  },
  "overview.deleted_items_toast": {
    one: "{n} Gegenstand gelöscht",
    other: "{n} Gegenstände gelöscht",
  },
  "overview.bulk_edit_title": {
    one: "{n} Gegenstand bearbeiten",
    other: "{n} Gegenstände bearbeiten",
  },
  "overview.change_location_label": "Standort ändern",
  "overview.change_quantity_label": "Menge ändern",
  "overview.quantity_type_label": "Mengenart",
  "overview.countable_option": "Zählbar",
  "overview.uncountable_option": "Unzählbar",
  "overview.amount_note_label": "Mengenhinweis",
  "overview.amount_note_placeholder": "z. B. halber Sack",
  "overview.apply_to_items_btn": {
    one: "Auf {n} Gegenstand anwenden",
    other: "Auf {n} Gegenstände anwenden",
  },
  "overview.choose_at_least_one_warning": "Wähle mindestens etwas zum Ändern aus",
  "overview.room_required_warning": "Raum ist erforderlich, um den Standort zu ändern",
  "overview.updated_items_toast": {
    one: "{n} Gegenstand aktualisiert",
    other: "{n} Gegenstände aktualisiert",
  },
  "overview.filter_shelf_modal_title": "Nach Regal filtern",
  "overview.search_shelves_placeholder": "Regale durchsuchen…",
  "overview.no_shelves_match": "Keine Regale passen",
  "overview.name_label": "Name",
  "overview.description_label": "Beschreibung",
  "overview.aliases_label": "Aliase (kommagetrennt)",
  "overview.no_room_set_option": "Kein Raum festgelegt",
  "overview.no_rooms_yet_note": "Noch keine Räume — füge einen unter Einstellungen → Räume verwalten hinzu.",
  "overview.photo_label": "Foto",
  "overview.save_changes_btn": "Änderungen speichern",
  "overview.delete_item_title": "Gegenstand löschen",
  "overview.delete_item_message": '„{name}“ löschen? Das kann nicht rückgängig gemacht werden.',
  "overview.item_updated_toast": "Gegenstand aktualisiert",
  "overview.item_deleted_toast": "Gegenstand gelöscht",
  "overview.location_label": "Standort",
  "overview.add_item_modal_title": "Gegenstand hinzufügen",
  "overview.save_add_another_btn": "Speichern & weiteren hinzufügen",
  "overview.save_close_btn": "Speichern & schließen",
  "overview.lightbox_close_aria": "Schließen",
};
