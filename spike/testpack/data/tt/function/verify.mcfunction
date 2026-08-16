# Spike fixture: the Q3 items that were inferred from structure but never
# confirmed on screen. Each line puts a translate component in one specific
# field. Every one of them should render as a real block name, not as the raw
# key "block.minecraft.*".
#
# Run with: /function tt:verify
#
# Expected if translate is honoured:
#   diamond_block  -> 鑽石方塊 / Block of Diamond
#   gold_block     -> 金磚     / Block of Gold
#   emerald_block  -> 綠寶石磚 / Block of Emerald

clear @s

# --- item_name (NOT the same component as custom_name) ---
give @s minecraft:stone[minecraft:item_name={translate:"block.minecraft.diamond_block"}]

# --- custom_name, already confirmed, kept as the control ---
give @s minecraft:apple[minecraft:custom_name={translate:"block.minecraft.gold_block"}]

# --- lore lines ---
give @s minecraft:stick[minecraft:custom_name={text:"LORE TEST - hover me"},minecraft:lore=[{translate:"block.minecraft.emerald_block"},{translate:"block.minecraft.gold_block"}]]

# --- written book page content (title is expected to FAIL, page should work) ---
give @s minecraft:written_book[minecraft:written_book_content={title:"page-translate-test",author:"spike",pages:[{translate:"block.minecraft.diamond_block"},{text:"page 2 is plain"}]}]

# --- team display name: printed by /team list ---
team list

# --- text_display: put a fresh one right in front of the player ---
kill @e[type=minecraft:text_display,tag=tt_verify]
summon minecraft:text_display ^ ^1 ^3 {text:{translate:"block.minecraft.diamond_block"},billboard:"center",Tags:["tt_verify"],background:1073741824}

say ---- checklist ----
say 1. hotbar slot 1 stone      -> item_name
say 2. hotbar slot 2 apple      -> custom_name (control, known good)
say 3. hotbar slot 3 stick      -> hover for lore
say 4. hotbar slot 4 book       -> open it, page 1
say 5. chat above               -> /team list output
say 6. floating text in front   -> text_display
say 7. the sign at 5 -60 6      -> compare FRONT and BACK
