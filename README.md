# AI Detective

Janhavi Bhattad · Activity-Based Assessment, Generative AI in Gaming

AI Detective is a small murder-mystery game. You type in a place, say "a Bollywood film set" or "a hostel during
a power cut", and a language model writes a new case set there. Each case has a victim, four suspects, four
locations to search and a hidden solution. You question the suspects, look for evidence and then name the killer.
Since every case is written on the spot, no two games are the same.

## How the game works

You get a fixed number of turns: 15 on Easy, 12 on Normal, 8 on Hard. Each of these actions uses up one turn:

- asking a suspect a question (you type whatever you want to ask),
- searching a location, which reveals any clues hidden there,
- asking your partner for a hint.

Each suspect is played by the AI. The innocent ones tell the truth about the murder, though they might hide
some unrelated personal secret. The killer lies and sticks to their alibi. But if you bring up a clue that
contradicts their story, they get defensive and slip up a bit. Most of the fun is in catching that.

Once you think you know, open the Accuse tab, pick a suspect and explain your reasoning. Making the accusation
doesn't cost a turn, but it ends the game. If you're right you score 100 points plus 10 for every turn you had left.
If you're wrong you score 0. Either way the AI writes the final scene and grades your reasoning as Sharp, Lucky
or Off track. Run out of turns and all you can do is accuse.

## Tools

- Python 3 with Streamlit for the interface
- Groq's API, using the `openai/gpt-oss-120b` model
- python-dotenv, so the API key stays in a `.env` file and out of the code
- unittest and Streamlit's AppTest for the tests

I started out planning to use Llama 3.3 on Groq. When I tested it, Groq had retired that model, so I moved to
GPT-OSS 120B. This one is a reasoning model, and its hidden "thinking" counts towards the reply length. At first
that cut off the end of the generated case, so I set its reasoning effort to low. You can switch models by
changing `GROQ_MODEL` in `.env`.

## How to run it

```bash
python3 -m venv .venv
source .venv/bin/activate          # on Windows: .venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env               # then paste your Groq key into .env
streamlit run app.py
```

The game opens at http://localhost:8501. You can get a free key at https://console.groq.com/keys.

The tests don't need a key, because the AI is replaced with fixed replies: `python -m unittest -v`

## Where the generative AI is used

All the AI calls live in `ai.py`. The AI is used in four places, and each one runs while you're playing:

1. Writing the case (`generate_case`). The model gets the player's setting and returns the whole case as
   JSON. A model can return a broken case, for example two killers or a clue in a room that doesn't exist.
   So `validate_case` in `game.py` checks it first, and if something is wrong the game asks the model once more.
2. Playing the suspects (`interrogate`). Every question is sent with that suspect's personality, alibi, secret
   and whether they're guilty. It also includes everything said in the interview so far and the clues the player
   has already found. That last part is what lets the killer react when you confront them with evidence.
3. The partner's hints (`partner_hint`). The model is given the solution plus what the player has and hasn't
   done, and is told to point them in a useful direction without naming the killer.
4. The ending (`write_ending`). The model writes the reveal scene and grades the player's explanation.

Everything the AI writes has a small "AI-written" label on screen. The backup case is marked "Hand-written".

## Handling errors

- Empty questions and questions over 300 characters are rejected. You can't search the same place twice, and
  you can't take actions once your turns are used up. You also have to tick a confirmation box before accusing.
- If the API key is missing or wrong, if you hit Groq's rate limit, or if the internet drops, the game shows a
  short message explaining what happened instead of crashing. The Groq library already retries network errors and
  rate limits a couple of times.
- If an AI call fails, you don't lose the turn.
- If the AI can't be reached at all, there's a hand-written backup case (`backup_case.json`) so the game can
  still be shown. If only the ending fails, the plain solution is shown instead.

## Files

- `app.py`: the screens (start, investigation, ending)
- `ai.py`: the prompts and every call to Groq
- `game.py`: the rules (turns, searching, accusing, scoring, checking AI cases). No AI code in here, so it can be tested on its own
- `backup_case.json`: the hand-written backup case
- `style.css` and `.streamlit/config.toml`: the case-file look
- `test_game.py`: tests, including one that plays a whole game through the interface

## Demo plan

1. Enter a setting, e.g. "a cricket stadium during the IPL final", and open the case file.
2. Search a couple of locations so some evidence shows up in the notebook.
3. Ask a suspect where they were, then mention one of the clues and watch the answer change.
4. Ask the partner for a hint.
5. Accuse someone, give a reason, and show the ending and the grade.
6. To show error handling, submit an empty question. Or rename `.env`, start a new game, and show the error
   message and the backup case.
