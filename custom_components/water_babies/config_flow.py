"""Config flow for Water Babies integration."""
import logging
import voluptuous as vol

from homeassistant.config_entries import ConfigFlow, ConfigFlowResult
from homeassistant.core import HomeAssistant
from homeassistant.const import CONF_USERNAME, CONF_PASSWORD
from homeassistant.exceptions import HomeAssistantError

from .water_babies_api import WaterBabiesAPI

_LOGGER = logging.getLogger(__name__)

DATA_SCHEMA = vol.Schema({
    vol.Required(CONF_USERNAME): str,
    vol.Required(CONF_PASSWORD): str,
})


class WaterBabiesConfigFlow(ConfigFlow, domain="water_babies"):
    """Handle a config flow for Water Babies."""

    VERSION = 1

    async def async_step_user(self, user_input=None) -> ConfigFlowResult:
        """Handle the initial step."""
        errors = {}
        if user_input is not None:
            try:
                info = await validate_input(self.hass, user_input)
            except CannotConnect:
                errors["base"] = "cannot_connect"
            except InvalidAuth:
                errors["base"] = "invalid_auth"
            except Exception:  # pylint: disable=broad-except
                _LOGGER.exception("Unexpected exception")
                errors["base"] = "unknown"
            else:
                return self.async_create_entry(title=info["title"], data=user_input)

        return self.async_show_form(
            step_id="user", data_schema=DATA_SCHEMA, errors=errors
        )


async def validate_input(hass: HomeAssistant, data: dict) -> dict:
    """Validate the user input allows us to connect.

    Data has the keys from DATA_SCHEMA with values provided by the user.
    """
    api = WaterBabiesAPI(hass, data[CONF_USERNAME], data[CONF_PASSWORD])

    try:
        await api.async_login()
    except RuntimeError as err:
        if "Login appears to have failed" in str(err):
            raise InvalidAuth from err
        raise CannotConnect from err

    # Return info that you want to store in the config entry.
    return {"title": data[CONF_USERNAME]}


class CannotConnect(HomeAssistantError):
    """Error to indicate we cannot connect."""


class InvalidAuth(HomeAssistantError):
    """Error to indicate there is invalid authentication."""
