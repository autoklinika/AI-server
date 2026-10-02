"""CPU-testable full-pass schedule and loss mask, without GPU imports."""

def step_groups(count, steps=64):
    if steps != 64 or count != 247:
        raise ValueError('review required for changed bounded training schedule')
    return [list(range(i * count // steps, (i + 1) * count // steps)) for i in range(steps)]


def tokenize_example(tok, row, max_length):
    prompt = [{'role': 'system', 'content': row['system']}, {'role': 'user', 'content': row['user']}]
    full = prompt + [{'role': 'assistant', 'content': row['assistant']}]
    prefix = tok.apply_chat_template(prompt, tokenize=False, add_generation_prompt=True)
    text = tok.apply_chat_template(full, tokenize=False, add_generation_prompt=False)
    prefix_ids = tok(prefix, add_special_tokens=False)['input_ids']
    ids = tok(text, add_special_tokens=False)['input_ids']
    if len(ids) > max_length:
        raise ValueError(f'full answer would be truncated: {row["record_id"]}: {len(ids)} > {max_length}')
    if ids[:len(prefix_ids)] != prefix_ids or len(prefix_ids) >= len(ids):
        raise ValueError('chat-template prompt prefix mismatch or empty answer')
    return ids, [-100] * len(prefix_ids) + ids[len(prefix_ids):]
