
VOICE_GENERATION_MODIFIER = 0.3

def calculate_query_cost(voice_message_string: str) -> int:
    token_cost = len(voice_message_string) * VOICE_GENERATION_MODIFIER
    return int(token_cost)