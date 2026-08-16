# Spike fixture: translatable text living inside a .mcfunction file.
#
# This file is itself a translation source - the tool must parse commands and
# find the text components embedded in them. Nothing here is written to NBT,
# which is exactly why it is a separate problem from the world scan.
#
# Run with: /function tt:messages

tellraw @a {"text":"TT_FUNC_TELLRAW_TEXT","color":"gold"}
tellraw @a [{"text":"TT_FUNC_TELLRAW_ARRAY_1"},{"text":"TT_FUNC_TELLRAW_ARRAY_2","bold":true}]
tellraw @a {"translate":"block.minecraft.diamond_block"}
title @a title {"text":"TT_FUNC_TITLE_TEXT"}
title @a subtitle {"text":"TT_FUNC_SUBTITLE_TEXT"}
title @a actionbar {"text":"TT_FUNC_ACTIONBAR_TEXT"}
give @s minecraft:stone[minecraft:custom_name={text:"TT_FUNC_GIVE_ITEM_NAME"},minecraft:lore=[{text:"TT_FUNC_GIVE_LORE"}]]
summon minecraft:armor_stand ~ ~ ~ {CustomName:{text:"TT_FUNC_SUMMON_NAME"},CustomNameVisible:1b}

# hover/click events nest yet another layer of text
tellraw @a {"text":"TT_FUNC_HOVER_BASE","hover_event":{"action":"show_text","value":{"text":"TT_FUNC_HOVER_TEXT"}}}
