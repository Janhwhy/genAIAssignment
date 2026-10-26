# AI Detective

Janhavi Bhattad · Activity-Based Assessment, Generative AI in Gaming

AI Detective is a small mystery game. You pick a setting and a crime, and a language model writes a new case
for you. There are eight ready-made settings, such as a Bollywood film set, an IPL final, a royal wedding or a
Mars base. You can also type your own idea, or press "Surprise me" and let the AI choose. The crime can be a
murder, a theft, a disappearance or a sabotage. Each case has four suspects, four locations to search and a
hidden solution. You question the suspects, look for evidence and then name the culprit. Since every case is
written on the spot, no two games are the same.

## How the game works

You get a fixed number of turns: 15 on Easy, 12 on Normal, 8 on Hard. Each of these actions uses up one turn:

- asking a suspect a question (type your own, or tap one of the quick questions),
- searching a location, which reveals any clues hidden there,
- asking your partner for a hint.

Each suspect is played by the AI. The innocent ones tell the truth about the crime, though they might hide
some unrelated personal secret. The culprit lies and sticks to their alibi. When you question someone, you can
also show them a piece of evidence you've found. An innocent suspect explains it honestly, but the culprit
comes up with an excuse that doesn't quite fit. Most of the fun is in catching that. Answers stream in word
by word, so you're never staring at a spinner.

The case also fights back while you work. These rules are plain Python in `game.py`, not AI:

- **Nerve.** Every suspect has a nerve meter. Show them evidence that really points at them and it goes up.
  After two different pieces they crack, and their secret is logged as a free exhibit. An innocent's secret
  explains away the red herring; the culprit's secret is how they did it.
- **The sealed room.** The location with the most evidence against the culprit starts sealed. Log two pieces of
  evidence and you get a warrant to search it.
- **A witness.** A third of the way through, a witness comes forward with a free clue.
- **The clean-up.** Halfway through, someone heads for a location you haven't searched yet. Get there within
  two turns or one piece of evidence is destroyed.

Each clue in a case is tagged with the suspect it casts suspicion on (`points_to`), which is what drives these rules.

Once you think you know, open the Accuse tab and fill in the deduction board: who did it, why (pick the motive)
and which exhibit proves it. You can also explain your reasoning in your own words. Making the accusation
doesn't cost a turn, but it ends the game. If you're right you score 100, plus 40 for the motive, 40 for the key
evidence, 10 for every turn you had left and 20 if you never asked for a hint. If you're wrong you score 0. You
earn up to three stars (culprit, motive, evidence) and a rank: Master Detective (three stars with a quarter of
your turns left), Inspector (two stars) or Constable. The AI writes the final scene and grades your reasoning as
Sharp, Lucky or Off track. Run out of turns and all you can do is accuse.

Your results are saved to `case_history.json`, so the start screen shows your career: cases played, solved,
best score and your current winning streak.

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

1. Writing the case (`generate_case`). The model gets the player's setting and the type of crime, and returns
   the whole case as JSON. A model can return a broken case, for example two culprits or a clue in a room that
   doesn't exist.
   So `validate_case` in `game.py` checks it first, and if something is wrong the game asks the model once more.
2. Playing the suspects (`interrogate`). Every question is sent with that suspect's personality, alibi, secret
   and whether they're guilty. It also includes everything said in the interview so far and the clues the player
   has already found. If the player shows them an exhibit, it is attached to the question in [brackets], and
   the prompt tells the suspect to react to that specific piece of evidence.
3. The partner's hints (`partner_hint`). The model is given the solution plus what the player has and hasn't
   done, and is told to point them in a useful direction without naming the culprit.
4. The ending (`write_ending`). The model writes the reveal scene and grades the player's explanation.

Everything the AI writes has a small "AI-written" label on screen. The backup cases are marked "Hand-written".

## Handling errors

- Empty questions and questions over 300 characters are rejected. You can't search the same place twice, and
  you can't take actions once your turns are used up. You also have to tick a confirmation box before accusing.
- If the API key is missing or wrong, if you hit Groq's rate limit, or if the internet drops, the game shows a
  short message explaining what happened instead of crashing. The Groq library already retries network errors and
  rate limits a couple of times. If Groq rejects a generated case as broken JSON, the game asks once more.
- If an AI call fails, you don't lose the turn.
- If the AI can't be reached at all, there are three hand-written backup cases (`backup_cases.json`: a murder,
  a theft and a sabotage) so the game can still be shown. If only the ending fails, the plain solution is shown instead.

## Files

- `app.py`: the screens (start, investigation, ending)
- `ai.py`: the prompts and every call to Groq
- `game.py`: the rules (turns, searching, accusing, scoring, checking AI cases). No AI code in here, so it can be tested on its own
- `backup_cases.json`: three hand-written backup cases
- `style.css` and `.streamlit/config.toml`: the case-file look
- `test_game.py`: tests, including one that plays a whole game through the interface

## Demo plan

1. Pick a setting card (or type your own idea), choose a crime, and open the case file.
2. Search a couple of locations so some evidence shows up in the notebook.
3. Ask a suspect where they were. Then ask again, this time showing them an exhibit, and watch the answer change.
4. Ask the partner for a hint.
5. Accuse someone, give a reason, and show the ending and the grade.
6. To show error handling, submit an empty question. Or rename `.env`, start a new game, and show the error
   message and the backup case.
