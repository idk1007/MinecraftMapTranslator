# Spike fixture generator.
#
# Every literal below is a unique GREPPABLE marker so the probe script can prove
# which NBT path each one landed in. Markers starting with TT_ are plain text;
# markers using a vanilla translate key test whether that field honours
# {"translate": ...} at all (Q3).
#
# Run once with: /function tt:setup

# --- a clean stone platform so nothing pops off ---
fill ~-2 ~-1 ~-2 ~12 ~-1 ~8 minecraft:stone
fill ~-2 ~ ~-2 ~12 ~4 ~8 minecraft:air

# =====================================================================
# SIGNS  (1.20+ front_text / back_text / messages)
# =====================================================================
setblock ~0 ~ ~0 minecraft:oak_sign[rotation=8]{front_text:{messages:[{text:"TT_SIGN_FRONT_1"},{text:"TT_SIGN_FRONT_2"},{text:"TT_SIGN_FRONT_3"},{text:"TT_SIGN_FRONT_4"}],color:"red",has_glowing_text:1b},back_text:{messages:[{text:"TT_SIGN_BACK_1"},{text:"TT_SIGN_BACK_2"},{text:""},{text:""}]},is_waxed:0b}

# sign carrying a translate component -> does it render translated? (Q3)
setblock ~1 ~ ~0 minecraft:oak_sign[rotation=8]{front_text:{messages:[{translate:"block.minecraft.diamond_block"},{text:"TT_SIGN_TRANSLATE_PROBE"},{text:""},{text:""}]}}

# hanging sign, different block entity id but same text layout
setblock ~2 ~2 ~0 minecraft:oak_hanging_sign{front_text:{messages:[{text:"TT_HANGSIGN_FRONT_1"},{text:""},{text:""},{text:""}]},back_text:{messages:[{text:"TT_HANGSIGN_BACK_1"},{text:""},{text:""},{text:""}]}}

# =====================================================================
# CONTAINERS + ITEM DATA COMPONENTS (1.20.5+)
# =====================================================================
setblock ~4 ~ ~0 minecraft:chest{CustomName:{text:"TT_CHEST_CUSTOM_NAME"}}

# custom_name + lore, the bread and butter of adventure maps
item replace block ~4 ~ ~0 container.0 with minecraft:diamond_sword[minecraft:custom_name={text:"TT_ITEM_CUSTOM_NAME",italic:false},minecraft:lore=[{text:"TT_ITEM_LORE_1"},{text:"TT_ITEM_LORE_2"}]]

# item_name is a *different* component from custom_name
item replace block ~4 ~ ~0 container.1 with minecraft:stone[minecraft:item_name={text:"TT_ITEM_NAME_COMPONENT"}]

# does custom_name honour translate? (Q3)
item replace block ~4 ~ ~0 container.2 with minecraft:apple[minecraft:custom_name={translate:"block.minecraft.diamond_block"},minecraft:lore=[{translate:"block.minecraft.gold_block"}]]

# written book: title is a plain string, pages are components - suspect asymmetry (Q3)
item replace block ~4 ~ ~0 container.3 with minecraft:written_book[minecraft:written_book_content={title:"TT_BOOK_TITLE",author:"TT_BOOK_AUTHOR",pages:[{text:"TT_BOOK_PAGE_1"},{text:"TT_BOOK_PAGE_2"}]}]

# book whose title is a translate key -> expected to render literally (Q3)
item replace block ~4 ~ ~0 container.4 with minecraft:written_book[minecraft:written_book_content={title:"block.minecraft.diamond_block",author:"TT_BOOK2_AUTHOR",pages:[{translate:"block.minecraft.diamond_block"}]}]

# unsigned draft book - plain strings, no components
item replace block ~4 ~ ~0 container.5 with minecraft:writable_book[minecraft:writable_book_content={pages:["TT_DRAFT_PAGE_1"]}]

# nested container: shulker box inside a chest, to prove recursion is required
item replace block ~4 ~ ~0 container.6 with minecraft:shulker_box[minecraft:custom_name={text:"TT_SHULKER_OUTER_NAME"},minecraft:container=[{slot:0,item:{id:"minecraft:emerald",count:1,components:{"minecraft:custom_name":{text:"TT_NESTED_ITEM_NAME"}}}}]]

# custom_data - maps stash arbitrary junk here, must NOT be blindly translated
item replace block ~4 ~ ~0 container.7 with minecraft:stick[minecraft:custom_data={quest_id:"TT_CUSTOM_DATA_SHOULD_BE_SKIPPED",tier:3}]

# lectern holding a book (block entity wrapping an item)
setblock ~5 ~ ~0 minecraft:lectern[has_book=true]{Book:{id:"minecraft:written_book",count:1,components:{"minecraft:written_book_content":{title:"TT_LECTERN_BOOK_TITLE",author:"TT_LECTERN_AUTHOR",pages:[{text:"TT_LECTERN_PAGE_1"}]}}}}

# =====================================================================
# ENTITIES
# =====================================================================
summon minecraft:armor_stand ~0 ~ ~3 {CustomName:{text:"TT_ARMORSTAND_NAME"},CustomNameVisible:1b,NoGravity:1b,Invulnerable:1b}
summon minecraft:armor_stand ~1 ~ ~3 {CustomName:{translate:"block.minecraft.diamond_block"},CustomNameVisible:1b,NoGravity:1b,Invulnerable:1b}
summon minecraft:cow ~2 ~ ~3 {CustomName:{text:"TT_COW_NAME"},CustomNameVisible:1b,NoAI:1b}
summon minecraft:villager ~3 ~ ~3 {CustomName:{text:"TT_VILLAGER_NAME"},CustomNameVisible:1b,NoAI:1b}

# text_display - modern maps use these instead of armor stands
summon minecraft:text_display ~4 ~1 ~3 {text:{text:"TT_TEXTDISPLAY_PLAIN"},billboard:"center"}
summon minecraft:text_display ~5 ~1 ~3 {text:{translate:"block.minecraft.diamond_block"},billboard:"center"}

# item frame on a wall, holding a renamed item
setblock ~7 ~ ~3 minecraft:stone
summon minecraft:item_frame ~7 ~1 ~3 {Facing:1b,Invisible:0b,Item:{id:"minecraft:diamond",count:1,components:{"minecraft:custom_name":{text:"TT_FRAMED_ITEM_NAME"}}}}

# =====================================================================
# COMMAND BLOCKS (text hides *inside* the command string)
# =====================================================================
setblock ~0 ~ ~6 minecraft:command_block{Command:"say TT_CMDBLOCK_SAY_TEXT",CustomName:{text:"TT_CMDBLOCK_CUSTOM_NAME"}}
setblock ~1 ~ ~6 minecraft:command_block{Command:'tellraw @a {"text":"TT_CMDBLOCK_TELLRAW_TEXT","color":"gold"}'}
setblock ~2 ~ ~6 minecraft:command_block{Command:'give @s minecraft:stone[minecraft:custom_name={text:"TT_CMDBLOCK_NESTED_ITEM_NAME"}]'}
setblock ~3 ~ ~6 minecraft:command_block{Command:'title @a title {"text":"TT_CMDBLOCK_TITLE_TEXT"}'}

# =====================================================================
# SCOREBOARD / TEAMS / BOSSBAR  (-> data/scoreboard.dat, level.dat)
# =====================================================================
scoreboard objectives add tt_plain dummy {"text":"TT_OBJECTIVE_DISPLAY"}
scoreboard objectives add tt_trans dummy {"translate":"block.minecraft.diamond_block"}
scoreboard objectives setdisplay sidebar tt_plain

team add tt_team {"text":"TT_TEAM_DISPLAY"}
team modify tt_team prefix {"text":"TT_TEAM_PREFIX_"}
team modify tt_team suffix {"text":"_TT_TEAM_SUFFIX"}
team add tt_team2 {"translate":"block.minecraft.diamond_block"}

bossbar add tt:bar {"text":"TT_BOSSBAR_NAME"}
bossbar set tt:bar players @a
bossbar add tt:bar2 {"translate":"block.minecraft.diamond_block"}
bossbar set tt:bar2 players @a

say TT_SETUP_DONE - now run /function tt:messages, then save and quit
