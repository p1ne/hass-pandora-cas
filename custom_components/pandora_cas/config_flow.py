"""Config flow for Pandora Car Alarm System component."""
__all__ = ("PandoraCASConfigFlow", "PandoraCASOptionsFlow")

import logging
from typing import Any, Dict, Final, List, Optional, TypeVar

import voluptuous as vol
from homeassistant import config_entries
from homeassistant.const import (
    CONF_PASSWORD,
    CONF_USERNAME,
    CONF_VERIFY_SSL,
    CONF_ACCESS_TOKEN,
)
from homeassistant.core import callback
from homeassistant.data_entry_flow import FlowResult, FlowResultType
from homeassistant.exceptions import ConfigEntryNotReady, ConfigEntryAuthFailed
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from custom_components.pandora_cas import async_run_pandora_coro
from custom_components.pandora_cas.api import (
    PandoraOnlineAccount,
)
from custom_components.pandora_cas.const import DOMAIN, CONF_DISABLE_WEBSOCKETS

_LOGGER = logging.getLogger(__name__)

STEP_USER_DATA_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_USERNAME): str,
        vol.Required(CONF_PASSWORD): str,
        vol.Optional(CONF_VERIFY_SSL, default=True): bool,
    }
)


@config_entries.HANDLERS.register(DOMAIN)
class PandoraCASConfigFlow(config_entries.ConfigFlow):
    """Handle a config flow for Pandora Car Alarm System config entries."""

    CONNECTION_CLASS: Final[str] = config_entries.CONN_CLASS_CLOUD_PUSH
    VERSION: Final[int] = 5

    def __init__(self) -> None:
        """Init the config flow."""
        self._reauth_entry: Optional[config_entries.ConfigEntry] = None

    async def _create_entry(self, config: Dict[str, Any]) -> Dict[str, Any]:
        """
        Finalize flow and create account entry.
        :param config: Configuration for account
        :return: (internal) Entry creation command
        """

        _LOGGER.debug(f"Creating entry for username {config[CONF_USERNAME]}")

        return self.async_create_entry(
            title=config[CONF_USERNAME],
            data={
                CONF_USERNAME: config[CONF_USERNAME],
                CONF_PASSWORD: config[CONF_PASSWORD],
            },
            options={
                CONF_VERIFY_SSL: config[CONF_VERIFY_SSL],
                CONF_DISABLE_WEBSOCKETS: False,
            },
        )

    async def async_step_user(
        self, user_input: Optional[Dict[str, Any]] = None
    ) -> FlowResult:
        if user_input is not None:
            account = PandoraOnlineAccount(
                username=user_input[CONF_USERNAME],
                password=user_input[CONF_PASSWORD],
                access_token=user_input.get(CONF_ACCESS_TOKEN),
                session=async_get_clientsession(
                    self.hass, verify_ssl=user_input[CONF_VERIFY_SSL]
                ),
            )

            try:
                await async_run_pandora_coro(account)
            except ConfigEntryAuthFailed:
                error = "invalid_auth"
            except ConfigEntryNotReady:
                error = "cannot_connect"
            else:
                unique_id = str(account.user_id)
                if entry := self._reauth_entry:
                    # Handle reauthentication
                    if unique_id != self._reauth_entry.unique_id:
                        await self.async_set_unique_id(unique_id)
                        self._abort_if_unique_id_configured()

                    self.hass.config_entries.async_update_entry(
                        entry,
                        title=user_input[CONF_USERNAME],
                        unique_id=unique_id,
                        data={
                            **entry.data,
                            CONF_USERNAME: user_input[CONF_USERNAME],
                            CONF_PASSWORD: user_input[CONF_PASSWORD],
                            CONF_ACCESS_TOKEN: account.access_token,
                        },
                        options={
                            **entry.options,
                            CONF_VERIFY_SSL: user_input[CONF_VERIFY_SSL],
                        },
                    )
                    await self.hass.config_entries.async_reload(entry.entry_id)
                    return self.async_abort(reason="reauth_successful")
                else:
                    # Handle new config entry
                    await self.async_set_unique_id(unique_id)
                    self._abort_if_unique_id_configured()

                    return self.async_create_entry(
                        title=user_input[CONF_USERNAME],
                        data={
                            CONF_USERNAME: user_input[CONF_USERNAME],
                            CONF_PASSWORD: user_input[CONF_PASSWORD],
                            CONF_ACCESS_TOKEN: account.access_token,
                        },
                        options={
                            CONF_VERIFY_SSL: user_input[CONF_VERIFY_SSL],
                            CONF_DISABLE_WEBSOCKETS: False,
                        },
                    )

            errors = {"base": error}
            schema = self.add_suggested_values_to_schema(
                STEP_USER_DATA_SCHEMA,
                user_input,
            )
        elif entry := self._reauth_entry:
            errors = {"base": "invalid_auth"}
            schema = self.add_suggested_values_to_schema(
                STEP_USER_DATA_SCHEMA,
                {**entry.data, **entry.options, CONF_PASSWORD: ""},
            )
        else:
            errors = None
            schema = STEP_USER_DATA_SCHEMA

        return self.async_show_form(
            step_id="user",
            data_schema=schema,
            errors=errors,
        )

    async def async_step_reauth(
        self, user_input: Optional[Dict[str, Any]] = None
    ) -> FlowResult:
        self._reauth_entry = self.hass.config_entries.async_get_entry(
            self.context["entry_id"]
        )
        return await self.async_step_user()

    async def async_step_import(
        self, user_input: Optional[Dict[str, Any]] = None
    ) -> FlowResult:
        if user_input is None:
            _LOGGER.error("Called import step without configuration")
            return self.async_abort("empty_configuration_import")

        result = await self.async_step_user(user_input)
        return (
            result
            if result["type"] == FlowResultType.CREATE_ENTRY
            else self.async_abort("unknown")
        )

    @staticmethod
    @callback
    def async_get_options_flow(
        config_entry: config_entries.ConfigEntry,
    ) -> config_entries.OptionsFlow:
        return PandoraCASOptionsFlow(config_entry)


class PandoraCASOptionsFlow(config_entries.OptionsFlow):
    def __init__(self, config_entry: config_entries.ConfigEntry):
        self.config_entry = config_entry
        self.use_text_fields = False
        self.config_codes: Optional[Dict[str, List[str]]] = None

    async def async_generate_schema_dict(
        self, user_input: Optional[Dict[str, Any]] = None
    ) -> Dict[vol.Marker, Any]:
        config_entry = self.config_entry

        # @TODO: reserved for future use
        final_config = {**config_entry.data, **config_entry.options}
        if user_input:
            final_config.update(user_input)

        schema_dict = {
            vol.Optional(CONF_PASSWORD): str,
        }

        return schema_dict

    async def async_step_init(
        self, user_input: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        if self.config_entry.source == config_entries.SOURCE_IMPORT:
            return self.async_abort(reason="yaml_not_supported")

        errors = {}
        if user_input:
            new_password = user_input.get(CONF_PASSWORD)
            if new_password:
                _LOGGER.debug("Password is getting updated")
                config_entry = self.config_entry

                self.hass.config_entries.async_update_entry(
                    config_entry,
                    data={
                        **config_entry.data,
                        CONF_PASSWORD: new_password,
                    },
                )

                # Setting data to None cancels double update
                return self.async_create_entry(title="", data=None)

            # Stub update
            return self.async_create_entry(title="", data=None)

        schema_dict = await self.async_generate_schema_dict(user_input)

        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema(schema_dict),
            errors=errors,
        )
