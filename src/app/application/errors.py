"""Errores de la aplicación. Las capas de infraestructura los lanzan y la capa de interfaces los traduce a HTTP."""


class InvalidCursor(Exception):
    """El cursor no es uno que el directorio haya emitido. Responde 400."""


class UpstreamUnavailable(Exception):
    """El directorio no puede responder (la réplica de técnicos aún no cargó). Responde 502: nunca una lista vacía, que
    parecería que no hay técnicos."""


class InvalidToken(Exception):
    """El access token no es válido (firma, vigencia, emisor, audiencia o claims obligatorios)."""


class RevocationCheckFailed(Exception):
    """No se pudo comprobar la revocación (la lista local no está al día). Se trata como token inválido (falla cerrado)."""


class AuthenticationFailed(Exception):
    """Falta la credencial o no es válida. Responde 401, siempre igual, sin explicar el motivo."""


class AccessDenied(Exception):
    """La credencial es válida pero su rol no permite la acción. Responde 403."""
