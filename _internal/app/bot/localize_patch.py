"""Translate what the bot sends, per player (see core/i18n.py): every reply to a slash command, button or menu passes
through the three Discord calls patched here, so no message needs to know about languages."""
import discord

from ..core.i18n import i18n

_done = False


def _embed(e: discord.Embed, t) -> discord.Embed:
    e = e.copy()
    e.title, e.description = t(e.title), t(e.description)
    for i, f in enumerate(e.fields):
        e.set_field_at(i, name=t(f.name), value=t(f.value), inline=f.inline)
    if e.footer and e.footer.text:
        e.set_footer(text=t(e.footer.text), icon_url=e.footer.icon_url)
    return e


def _view(v, t):
    for item in getattr(v, "children", []):
        if getattr(item, "label", None):
            item.label = t(item.label)
        if getattr(item, "placeholder", None):
            item.placeholder = t(item.placeholder)
        for o in getattr(item, "options", []) or []:
            o.label, o.description = t(o.label), t(o.description) if o.description else o.description


def localize_kwargs(user_id, kwargs: dict) -> dict:
    lang = i18n.player_language(user_id)
    if lang == "en":
        return kwargs
    t = lambda s: i18n.t(s, lang)
    out = dict(kwargs)
    if isinstance(out.get("content"), str):
        out["content"] = t(out["content"])
    if out.get("embed") is not None:
        out["embed"] = _embed(out["embed"], t)
    if out.get("embeds"):
        out["embeds"] = [_embed(e, t) for e in out["embeds"]]
    if out.get("view") is not None:
        _view(out["view"], t)
    return out


def install():
    """Patch discord.py once."""
    global _done
    if _done:
        return
    _done = True
    send, edit = discord.InteractionResponse.send_message, discord.InteractionResponse.edit_message
    edit_original = discord.Interaction.edit_original_response

    async def send_message(self, content=None, **kw):
        kw = localize_kwargs(self._parent.user.id, dict(kw, content=content))
        content = kw.pop("content")
        return await send(self, content, **kw)

    async def edit_message(self, **kw):
        kw = localize_kwargs(self._parent.user.id, kw)
        return await edit(self, **kw)

    async def edit_original_response(self, **kw):
        kw = localize_kwargs(self.user.id, kw)
        return await edit_original(self, **kw)

    discord.InteractionResponse.send_message = send_message
    discord.InteractionResponse.edit_message = edit_message
    discord.Interaction.edit_original_response = edit_original_response
