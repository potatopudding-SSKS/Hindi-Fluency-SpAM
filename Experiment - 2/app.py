import math
import os
import random
import time

import streamlit as st

try:
    from bson import ObjectId
    from pymongo import MongoClient
    MONGO_AVAILABLE = True
except ImportError:
    MONGO_AVAILABLE = False

MONGO_URI = os.environ.get("MONGO_URI", "")   # set this in your environment


def save_to_mongo(participant_dict: dict) -> bool:
    """Returns True on success, False on failure.

    The document's _id is fixed for the session, so retrying after a failure (e.g. the
    write reached the database but the reply was lost) overwrites the same document
    instead of adding a second copy."""
    if not MONGO_AVAILABLE:
        st.error("pymongo is not installed. Run: pip install pymongo")
        return False
    if not MONGO_URI:
        st.error("MONGO_URI environment variable is not set.")
        return False
    if "doc_id" not in st.session_state:
        st.session_state.doc_id = ObjectId()
    doc = {"_id": st.session_state.doc_id, **participant_dict}
    client = None
    try:
        client = MongoClient(MONGO_URI, serverSelectionTimeoutMS=5000)
        db = client["semantic_fluency_db"]
        col = db["participants"]
        col.replace_one({"_id": doc["_id"]}, doc, upsert=True)
        return True
    except Exception as exc:
        st.error(f"MongoDB error: {exc}")
        return False
    finally:
        if client is not None:
            client.close()


ALL_CATEGORIES = ["body_parts", "fruitsnveg", "animals"]

CAT2HI = {
    "body_parts":   "शरीर के अंगों",
    "fruitsnveg":   "फलों और सब्ज़ियों",
    "animals":      "जानवरों",
}

VFT_DURATION_SECONDS = 180   # Should be 180 in the release version

WAIT_DURATION_SECONDS = 30   # Should be 30 in the release version

# Verbal fluency input. Timing runs in the browser (performance.now()), so response times
# are not affected by network delay; each word is stored with the seconds since the input
# appeared. Repeats of an already-entered word are ignored, as before.
VFT_COMPONENT_HTML = """
<div class="vft-root">
    <div class="vft-timer">⏱ --:--</div>
    <label class="vft-label" for="vft-input">हर शब्द के बाद <strong>ENTER</strong> दबाएँ! कृपया <strong>अंग्रेज़ी अक्षरों</strong> का उपयोग करके <strong>हिंदी शब्द</strong> लिखें।</label>
    <input id="vft-input" class="vft-input" type="text" autocomplete="off" autocorrect="off" autocapitalize="off" spellcheck="false" />
    <div class="vft-done">
        <p>समय समाप्त! आगे बढ़ने के लिए नीचे दिया गया बटन दबाएँ।</p>
        <button class="vft-continue" type="button">आगे बढ़ें</button>
    </div>
</div>
"""

VFT_COMPONENT_CSS = """
.vft-root {
    display: flex;
    flex-direction: column;
    gap: 10px;
    width: 100%;
}

.vft-timer {
    font-size: 28px;
    font-weight: 700;
}

.vft-input {
    box-sizing: border-box;
    width: 100%;
    font: inherit;
    font-size: 18px;
    padding: 8px 10px;
    border: 1px solid #aaa;
    border-radius: 6px;
}

.vft-done {
    display: none;
}

.vft-continue {
    background-color: #2e9f5e;
    color: white;
    font-size: 18px;
    font-weight: 600;
    padding: 12px 28px;
    border: none;
    border-radius: 6px;
    box-shadow: 0 4px 10px rgba(0, 0, 0, 0.2);
    cursor: pointer;
}
"""

VFT_COMPONENT_JS = """
export default function(component) {
    const { data, parentElement, setTriggerValue } = component;
    const duration = Number(data?.duration_s) || 180;
    const timer = parentElement.querySelector(".vft-timer");
    const input = parentElement.querySelector(".vft-input");
    const done = parentElement.querySelector(".vft-done");
    const continueButton = parentElement.querySelector(".vft-continue");
    if (!timer || !input || !done || !continueButton) {
        return;
    }

    // Kept on the parent element: Streamlit can call this function again on a rerun,
    // and that must not restart the clock or lose the words entered so far.
    const state = parentElement.__vftState || (parentElement.__vftState = {
        start: performance.now(),
        entries: [],
        seen: new Set(),
        finished: false,
        tick: null,
    });

    function format(seconds) {
        const m = Math.floor(seconds / 60);
        const s = seconds % 60;
        return String(m).padStart(2, "0") + ":" + String(s).padStart(2, "0");
    }

    function finish() {
        state.finished = true;
        clearInterval(state.tick);
        timer.textContent = "⏱ 00:00";
        input.disabled = true;
        done.style.display = "block";
    }

    function update() {
        const remaining = Math.max(0, Math.ceil(duration - (performance.now() - state.start) / 1000));
        timer.textContent = "⏱ " + format(remaining);
        if (remaining <= 0) {
            finish();
        }
    }

    input.onkeydown = (event) => {
        if (event.key !== "Enter" || event.isComposing || state.finished) {
            return;
        }
        event.preventDefault();
        const word = input.value.trim();
        if (word && !state.seen.has(word)) {
            state.seen.add(word);
            // Seconds since the input appeared, to the millisecond
            state.entries.push([word, Math.round(performance.now() - state.start) / 1000]);
        }
        input.value = "";
    };

    continueButton.onclick = () => {
        setTriggerValue("finished", state.entries);
    };

    clearInterval(state.tick);
    if (state.finished) {
        finish();
    } else {
        update();
        state.tick = setInterval(update, 250);
        input.focus();
    }
    return () => clearInterval(state.tick);
}
"""

SPAM_COMPONENT_HTML = """
<div class="spam-root">
    <div id="word-drop-area" class="spam-plane" aria-label="Placement plane" tabindex="0"></div>
    <div class="spam-actions">
        <button class="spam-continue" type="button">आगे बढ़ें</button>
    </div>
</div>
"""

SPAM_COMPONENT_CSS = """
.spam-root {
    display: flex;
    flex-direction: column;
    gap: 12px;
    font-family: "Helvetica Neue", Arial, sans-serif;
    width: 100%;
    align-items: center;
}

.spam-plane {
    /* Square, so x and y are normalised by the same length on every screen */
    position: relative;
    box-sizing: border-box;
    margin: 24px auto 8px;
    width: min(100%, 70vh, 8192px);
    aspect-ratio: 1 / 1;
    border: 2px solid #aaa;
    padding: 20px;
    overflow: hidden;
}

.spam-box {
    display: inline-block;
    background: #eef;
    color: #1a1a1a;
    padding: 4px 8px;
    border: 1px solid #aaa;
    border-radius: 4px;
    cursor: grab;
    user-select: none;
    font-size: 14px;
    line-height: 1.2;
    margin-bottom: 4px;
    white-space: nowrap;
}

.spam-box:active {
    cursor: grabbing;
}

.spam-actions {
    display: flex;
    justify-content: center;
    width: 100%;
}

.spam-continue {
    display: none;
    margin-top: 20px;
    background-color: #2e9f5e;
    color: white;
    font-size: 18px;
    font-weight: 600;
    padding: 12px 28px;
    border: none;
    border-radius: 6px;
    box-shadow: 0 4px 10px rgba(0, 0, 0, 0.2);
    cursor: pointer;
}
"""

SPAM_COMPONENT_JS = """
export default function(component) {
    const { data, parentElement, setTriggerValue } = component;
    const words = Array.isArray(data?.words) ? data.words : [];

    const plane = parentElement.querySelector(".spam-plane");
    const continueButton = parentElement.querySelector(".spam-continue");
    if (!plane || !continueButton) {
        return;
    }

    const movedIds = new Set();
    const SPAWN_PX = 20;     // where each new word appears (left and top, in px)
    const MIN_MOVE_PX = 10;  // a word counts as placed once dropped this far from there

    function roundTo(value, digits) {
        const factor = Math.pow(10, digits);
        return Math.round(value * factor) / factor;
    }

    function clamp01(value) {
        return Math.min(1, Math.max(0, value));
    }

    function getCoords(element) {
        const dropRect = plane.getBoundingClientRect();
        const elemRect = element.getBoundingClientRect();
        if (dropRect.width === 0 || dropRect.height === 0) {
            return [0, 0];
        }
        const xPx = elemRect.left - dropRect.left;
        const yPx = elemRect.top - dropRect.top;
        const xCenter = xPx + elemRect.width / 2;
        const yCenter = yPx + elemRect.height / 2;
        const xNorm = clamp01(xCenter / dropRect.width);
        const yNorm = clamp01((dropRect.height - yCenter) / dropRect.height);
        return [roundTo(xNorm, 6), roundTo(yNorm, 6)];
    }

    function collectCoords() {
        const coords = {};
        plane.querySelectorAll(".spam-box").forEach((box) => {
            coords[box.dataset.word] = getCoords(box);
        });
        return coords;
    }

    function enableContinueIfReady() {
        if (movedIds.size === words.length) {
            continueButton.style.display = "inline-block";
        }
    }

    function draggable(element, onFirstPlaced) {
        let offsetX = 0;
        let offsetY = 0;
        let dragging = false;
        let placed = false;

        element.addEventListener("pointerdown", (event) => {
            dragging = true;
            element.setPointerCapture(event.pointerId);
            const rect = element.getBoundingClientRect();
            offsetX = event.clientX - rect.left;
            offsetY = event.clientY - rect.top;
            element.style.cursor = "grabbing";
            event.preventDefault();
        });

        element.addEventListener("pointermove", (event) => {
            if (!dragging) {
                return;
            }
            const dropRect = plane.getBoundingClientRect();
            let left = event.clientX - dropRect.left - offsetX;
            let top = event.clientY - dropRect.top - offsetY;

            left = Math.max(0, Math.min(left, dropRect.width - element.offsetWidth));
            top = Math.max(0, Math.min(top, dropRect.height - element.offsetHeight));

            element.style.left = left + "px";
            element.style.top = top + "px";
        });

        function endDrag(event) {
            if (!dragging) {
                return;
            }
            dragging = false;
            element.releasePointerCapture(event.pointerId);
            element.style.cursor = "grab";
            // A click, or a drop back where the word appeared, does not count as placing it
            const dx = parseFloat(element.style.left) - SPAWN_PX;
            const dy = parseFloat(element.style.top) - SPAWN_PX;
            if (!placed && Math.hypot(dx, dy) >= MIN_MOVE_PX) {
                placed = true;
                movedIds.add(element.dataset.wordId);
                enableContinueIfReady();
                if (typeof onFirstPlaced === "function") {
                    onFirstPlaced();
                }
            }
        }

        element.addEventListener("pointerup", endDrag);
        element.addEventListener("pointercancel", endDrag);
    }

    let currentIndex = 0;

    function nextWord() {
        if (currentIndex >= words.length) {
            return;
        }
        const word = words[currentIndex];
        const wordDiv = document.createElement("div");
        wordDiv.textContent = word;
        wordDiv.className = "spam-box";
        wordDiv.dataset.word = word;
        wordDiv.dataset.wordId = String(currentIndex);
        wordDiv.style.position = "absolute";
        wordDiv.style.left = SPAWN_PX + "px";
        wordDiv.style.top = SPAWN_PX + "px";

        plane.appendChild(wordDiv);
        draggable(wordDiv, () => {
            currentIndex += 1;
            setTimeout(() => {
                nextWord();
            }, 2000);
        });
    }

    continueButton.onclick = () => {
        if (movedIds.size !== words.length) {
            return;
        }
        const rect = plane.getBoundingClientRect();
        setTriggerValue("continue_clicked", {
            coords: collectCoords(),
            plane: [roundTo(rect.width, 1), roundTo(rect.height, 1)],
        });
    };

    while (plane.firstChild) {
        plane.removeChild(plane.firstChild);
    }
    continueButton.style.display = "none";
    movedIds.clear();
    currentIndex = 0;
    nextWord();
}
"""


def _build_steps():
    steps = [
        "consent",
        "gen_instructions",
        "vft_instructions",
        "vft_task_0",
        "spam_instructions",
        "spam_task_0",
        "distractor",
        "interval_1",
        "vft_task_1",
        "spam_task_1",
        "distractor",
        "interval_2",
        "vft_task_2",
        "spam_task_2",
        "exit_poll_instructions",
        "exit_poll_1",
        "exit_poll_2",
        "exit_poll_3",
        "exit_poll_4",
        "exit_poll_5",
        "exit_poll_6",
        "exit_poll_7",
        "exit_poll_8",
        "saving",
        "thank_you",
    ]
    return steps


# Session-state bootstrap
def _init():
    if "initialised" in st.session_state:
        return

    st.session_state.initialised = True
    st.session_state.steps = _build_steps()
    st.session_state.step_idx = 0

    # Randomised category order
    cat_order = ALL_CATEGORIES[:]
    random.shuffle(cat_order)
    st.session_state.cat_order = cat_order

    # Participant bag
    st.session_state.p = {
        "name": "",
        "rno": "",
        "categories": {},   # cat_name -> {"words_and_rts": [...], "words_and_coords": {...}}
    }

    # Distractor variable
    st.session_state.wait_start_time = None
    st.session_state.wait_end_time = None
    st.session_state.wait_timer_done = False

    # Exit-poll intermediates
    st.session_state.lang_list = []


def advance():
    st.session_state.step_idx += 1


def current_step():
    return st.session_state.steps[st.session_state.step_idx]


def answered(required: dict) -> bool:
    """required: {question label: answer}. Warns about unanswered mandatory questions and
    returns True only if every one has an answer."""
    missing = [
        label for label, value in required.items()
        if value is None or (isinstance(value, str) and not value.strip())
    ]
    if missing:
        st.warning("Please answer: " + "; ".join(missing))
        return False
    return True


def cat_for_step(step_name: str):
    """Return the category name for a vft_task_N or spam_task_N step."""
    idx = int(step_name.split("_")[-1])
    return st.session_state.cat_order[idx]


@st.fragment(run_every=1)
def _wait_timer_fragment(wait_seconds: int = 30):
    if st.session_state.wait_timer_done:
        st.rerun(scope="app")
        return
    
    now = time.time()
    elapsed = now - st.session_state.wait_start_time
    remaining = max(0, math.ceil(wait_seconds - elapsed))
    ready = remaining <= 0

    st.title("कृपया रुकें...")

    def _on_continue():
        st.session_state.wait_timer_done = True

    if ready:
        st.markdown(
            "<div style='font-size:20px;font-weight:600;color:green;'>"
            "<br>जब आप तैयार हों, तब आगे बढ़ें।<br><br>"
            "</div>",
            unsafe_allow_html=True,
        )
        st.button(
            "आगे बढ़ें",
            key="wait_continue_button",
            disabled=not ready,
            on_click=_on_continue,
        )
    else:
        st.markdown(
            f"<div style='font-size:28px;font-weight:700;'>⏱ {remaining}s</div>",
            unsafe_allow_html=True,
        )



# Page config 
st.set_page_config(
    page_title="Semantic Fluency Test",
    page_icon=":brain:",
    layout="centered",
)

_init()
step = current_step()



# Consent
if step == "consent":
    st.header("Please read the following:")
    st.markdown(
"""
**This is a consent form for research participation.** It holds valuable information about this study and what to expect if you decide to participate.

**Your participation is voluntary.**

Please consider the information carefully. Feel free to ask questions before making your decision to participate. If you decide to participate, you will be asked to sign this form and will receive a copy of the form.

**Purpose:** The purpose of the study is to investigate semantic memory organization and verbal fluency patterns in Hindi speakers.

**Procedures/Tasks:** You need to have a good internet connection for this experiment. For the time being, you will have to participate in two tasks:

1. **Verbal Fluency Task:** You will be shown a category name and asked to type as many words as you can from that category within a time limit.
2. **Spatial Arrangement Task:** You will organize the words you typed by arranging them spatially based on how similar they are to each other.

Although no identifiable information will be published, the responses you provide should not have any sensitive information (e.g., relating to illegal behaviors, alcohol or drug use, sexual attitudes, mental health, etc.) nor should you disclose any information that may place you at risk of criminal or civil liability.

You will be asked to answer questions based on the information you supplied earlier and that concludes the task.

**Duration:** Participating in the data collection phase of the study should take up to 30 minutes of your time. You may leave the study at any time. If you decide to stop participating in the study, there will be no penalty to you and your decision will not affect your future relationship with IIIT-Hyderabad.

**Risks and Benefits:** There are minimal anticipated risks to you because of participating in this study and no long-term consequences are expected. No identifiable information will be published. The data will be kept in electronic form on a secure server. You will not benefit directly from participating in the study.

**Confidentiality:** Efforts will be made to keep your study-related information confidential. However, there may be circumstances where this information must be released. For example, personal information on your participation in this study may be disclosed if required by state law. Also, your records may be reviewed by the following groups (as applicable to the research):

- Office for Human Research Protections or other federal, state, or international regulatory agencies.
- The IIIT (International Institute of Information Technology) Review Board or Office of Responsible Research Practices.
- The sponsor, if any, or agency supporting the study.

**Participant Rights:** If you are a student or employee at IIIT-Hyderabad, your decision to participate will not affect your grades or employment status.

If you choose to participate in the study, you may drop participation at any time. By signing this form, you do not give up any personal legal rights you may have as a participant in this study.

An Institutional Review Board responsible for human subjects' research at International Institute of Information Technology, Hyderabad (IIIT-H) reviewed this research project and found it to be acceptable, according to applicable state and federal regulations and University policies designed to protect the rights and welfare of participants in research.

**Contacts and Questions**
For questions, concerns, or complaints about the study you may contact:

1. K S Sai Sankalp (Email: kssaisankalp.davey@research.iiit.ac.in) or
2. Vishnu Sreekumar (Email: vishnu.sreekumar@iiit.ac.in)

**Signing the consent form**
I have read (or someone has read to me) this form, and I am aware that I am being asked to participate in a research study. I have had the opportunity to ask questions and have had them answered to my satisfaction. I agree to participate in this study.

I am not giving up any legal rights by signing this form. I will be given a copy of this form.

By signing this form, I verify that I am 18 years of age or older.

"""
    )
    with st.form("consent_form", clear_on_submit=True):
        name = st.text_input("Name*")
        rno  = st.text_input("Roll No.*")
        submitted = st.form_submit_button("I agree and wish to continue")
    if submitted:
        if not name.strip() or not rno.strip():
            st.warning("Please enter both your name and roll number.")
            st.stop()
        st.session_state.p["name"] = name.strip()
        st.session_state.p["rno"]  = rno.strip()
        advance()
        st.rerun()



# General Instructions
elif step == "gen_instructions":
    gen_block = st.container()
    with gen_block:
        st.text("इस अध्ययन में भाग लेने के लिए धन्यवाद!")
        st.title("इसमें दो चरण हैं:")
        st.markdown("<u>प्रथम चरण में</u>, आपको एक श्रेणी का नाम दिखाया जाएगा।", unsafe_allow_html=True)
        st.markdown(
            "आपको निर्धारित समय सीमा के भीतर उस श्रेणी से संबंधित जितने संभव हो सकें, "
            "उतने शब्द **हिंदी में** टाइप करने होंगे। \n\n जैसे \"कुत्ता\" -> \"kutta\"।"
        )
        st.markdown(
            "<u>दूसरे चरण में</u>, आपको पहले टाइप किए गए हर शब्द को ऐसे व्यवस्थित करना होगा कि समान अर्थ वाले शब्द एक-दूसरे के पास हों।",
            unsafe_allow_html=True,
        )
        st.markdown(
            "इस अध्ययन में सिर्फ़ 3 श्रेणियाँ होंगी, इसलिए कृपया जितनी हो सके उतनी सटीकता बनाए रखें।"
        )
        st.markdown(
            "टाइप करते समय अथवा शब्दों को व्यवस्थित करते समय, शीघ्रता की आवश्यकता नहीं है, सटीकता सबसे महत्वपूर्ण है।"
        )
        st.markdown("जब आप शुरू करने के लिए तैयार हों, **\"शुरू\" दबाएँ।**")
        start_clicked = st.button("शुरू")
    if start_clicked:
        gen_block.empty()
        advance()
        st.rerun()



# VFT Instructions
elif step == "vft_instructions":
    vft_block = st.container()
    with vft_block:
        st.title("**आप अभी एक वर्बल फ्लुएंसी टास्क करने वाले हैं।**")
        st.markdown(
            "इस चरण में आपको एक श्रेणी का नाम दिखाया जाएगा।"
        )
        st.markdown(
            "आपको 3 मिनट के भीतर दिखाई गई श्रेणी से संबंधित याद आने वाले सभी शब्द "
            "**हिंदी में** टाइप करने हैं।"
        )
        st.markdown("जैसे \"कुत्ता\" -> \"kutta\"।")
        st.markdown("आपको यह काम 3 अलग-अलग श्रेणियों पर करना होगा।")
        st.markdown("हर शब्द टाइप करने के बाद, अगला शब्द टाइप करने के लिए **ENTER** दबाएँ।")
        st.markdown("समय खत्म होने के बाद, आगे बढ़ने के लिए **आगे बढ़ें** दबाएँ।")
        st.markdown("जब आप तैयार हों, तो **शुरू** दबाएँ!")
        start_clicked = st.button("शुरू")
    if start_clicked:
        vft_block.empty()
        advance()
        st.rerun()



# VFT Task
elif step.startswith("vft_task_"):
    cat = cat_for_step(step)
    hi_cat = CAT2HI[cat]

    st.title(f"**{hi_cat}** के नाम बताएं, जितने आपको याद हों।")

    vft_component = st.components.v2.component(
            name="vft_input",
            html=VFT_COMPONENT_HTML,
            css=VFT_COMPONENT_CSS,
            js=VFT_COMPONENT_JS,
            isolate_styles=True,
    )

    result = vft_component(
            key=f"vft-input-{cat}",
            data={"duration_s": VFT_DURATION_SECONDS},
            on_finished_change=lambda: None,
    )

    # Sent once time is up and the participant clicks "आगे बढ़ें": [[word, seconds], ...]
    if result and result.finished is not None:
            st.session_state.p["categories"][cat] = {
                    "words_and_rts": [(str(word), float(seconds)) for word, seconds in result.finished],
                    "words_and_coords": {},
            }
            advance()
            st.rerun()



# SpAM Instructions
elif step == "spam_instructions":
    spam_instr_block = st.container()
    with spam_instr_block:
        st.title("अब, आप एक स्पेशियल अरेंजमेंट टास्क शुरू करेंगे।")
        st.markdown(
            "इस चरण में, आपको वे सभी शब्द एक-एक करके दिखाए जाएंगे "
            "जो आपने पिछले चरण में दर्ज किए थे।"
        )
        st.markdown(
            "हम यह जानना चाहते हैं कि आपके अनुसार आपके उत्तर कितने समान थे। "
            "आपको अपने सभी जवाब ऐसे व्यवस्थित करने हैं कि समान शब्द एक-दूसरे के पास हों।"
        )
        st.markdown(
            "*(पास होने का मतलब है ज़्यादा समानता, दूर होने का मतलब है ज़्यादा असमानता)*"
        )
        st.markdown(
            "शब्द एक क्षेत्र के ऊपरी बाएँ कोने में एक-एक करके दिखाई देंगे। "
            "बस उन्हें क्लिक और ड्रैग करके हिलाएँ।"
        )
        st.markdown(
            "हर शब्द को व्यवस्थित करने के बाद, 2 सेकंड में अगला शब्द आएगा। "
            "आप पहले से रखे गए शब्दों को फिर से व्यवस्थित कर सकते हैं।"
        )
        st.markdown(
            "**सभी** शब्दों को कम से कम एक बार व्यवस्थित करने के बाद ही "
            "\"आगे बढ़ें\" बटन दिखाई देगा।"
        )
        st.markdown("जब आप तैयार हों, तो **शुरू** दबाएँ।")
        start_clicked = st.button("शुरू")
    if start_clicked:
        spam_instr_block.empty()
        advance()
        st.rerun()



# SpAM Task
elif step.startswith("spam_task_"):
    cat   = cat_for_step(step)
    words = [
        w for w, _ in
        st.session_state.p["categories"].get(cat, {}).get("words_and_rts", [])
    ]

    if not words:
        st.warning("इस श्रेणी में कोई शब्द नहीं मिला। अगले चरण पर जाएं।")
        if st.button("आगे बढ़ें"):
            advance()
            st.rerun()
        st.stop()

    st.title("शब्दों को नीचे दिए गए क्षेत्र में व्यवस्थित करें।")
    st.markdown(
        "हर शब्द को कम से कम एक बार खिसकाएँ। सभी शब्द व्यवस्थित होने के बाद **आगे बढ़ें** बटन दिखाई देगा।"
    )

    spam_component = st.components.v2.component(
            name="spam_plane",
            html=SPAM_COMPONENT_HTML,
            css=SPAM_COMPONENT_CSS,
            js=SPAM_COMPONENT_JS,
            isolate_styles=True,
    )

    result = spam_component(
            key=f"spam-plane-{cat}",
            data={"words": words},
            on_continue_clicked_change=lambda: None,
    )

    if result and result.continue_clicked:
            # {"coords": {word: [x, y]}, "plane": [width_px, height_px]}
            payload = result.continue_clicked
            coords_raw = payload.get("coords") if isinstance(payload, dict) else None
            if isinstance(coords_raw, dict) and len(coords_raw) == len(words):
                    st.session_state.p["categories"][cat]["words_and_coords"] = {
                            word: (float(coords_raw[word][0]), float(coords_raw[word][1]))
                            for word in coords_raw
                    }
                    st.session_state.p["categories"][cat]["plane_px"] = [
                            float(v) for v in payload.get("plane") or []
                    ]
                    advance()
                    st.rerun()
            else:
                    st.warning("Coords mismatch - please try again.")


# Distractor
elif step == "distractor":
    if st.session_state.wait_end_time is None:
        st.session_state.wait_start_time = time.time()
        st.session_state.wait_end_time   = time.time() + WAIT_DURATION_SECONDS
        st.session_state.wait_timer_done = False
    if not st.session_state.wait_timer_done:
        _wait_timer_fragment(WAIT_DURATION_SECONDS)
    else:
        # The fragment's "आगे बढ़ें" button set wait_timer_done: move on straight away
        st.session_state.wait_end_time = None
        advance()
        st.rerun()

# Interval
elif step.startswith("interval_"):
    interval_block = st.container()
    with interval_block:
        st.header("अब आप अगली श्रेणी पर जाएंगे।")
        st.markdown(
            "याद दिलाने के लिए, इस चरण में आपको दी गई श्रेणी से जुड़े "
            "जितने भी शब्द याद आएं, उन सभी को टाइप करना है।"
        )
        st.markdown("शुरू करने के लिए **शुरू** दबाएँ।")
        start_clicked = st.button("शुरू")
    if start_clicked:
        interval_block.empty()
        advance()
        st.rerun()



# Exit Poll Instructions
elif step == "exit_poll_instructions":
    st.markdown("Now we would like to ask you some follow up questions")
    st.markdown("The questions marked by * are mandatory, those that are not can be left blank if you prefer not to answer them.")
    st.markdown("When you are ready, click the **Continue** button below to proceed.")
    if st.button("Continue"):
        advance()
        st.rerun()



# Exit Poll 1 - strats and language comfort
elif step == "exit_poll_1":
    st.header("Exit Poll")
    opts = [
        "Most Uncomfortable",
        "Moderately Uncomfortable",
        "Neutral",
        "Moderately Comfortable",
        "Most Comfortable",
    ]
    strats_1 = st.text_area("What strategies, if any, did you use while attempting the task for Animals?")
    strats_2 = st.text_area("What strategies, if any, did you use while attempting the task for Body Parts?")
    strats_3 = st.text_area("What strategies, if any, did you use while attempting the task for Fruits and Vegetables?")
    strats = [strats_1, strats_2, strats_3]
    hi_r = st.radio("How comfortable are you with reading Hindi in Devanagari?*",  opts, index=None, horizontal=True)
    hi_w = st.radio("How comfortable are you with writing Hindi in the English alphabet?*", opts, index=None, horizontal=True)
    en_r = st.radio("How comfortable are you with reading English?*",  opts, index=None, horizontal=True)
    en_w = st.radio("How comfortable are you with writing English?*", opts, index=None, horizontal=True)
    if st.button("Continue") and answered({
        "reading Hindi in Devanagari": hi_r,
        "writing Hindi in the English alphabet": hi_w,
        "reading English": en_r,
        "writing English": en_w,
    }):
        st.session_state.p.update(
            strats=strats, hi_r=hi_r, hi_w=hi_w, en_r=en_r, en_w=en_w
        )
        advance()
        st.rerun()



# Exit Poll 2 - languages
elif step == "exit_poll_2":
    st.header("Follow Up Questions:")
    first_lang = st.text_input("What is your first language?*")
    lang_count  = st.number_input("How many languages do you know?*", min_value=1, step=1, value=1)

    def _add_lang():
        lang = st.session_state._lang_input.strip()
        if lang and lang.lower() not in [l.lower() for l in st.session_state.lang_list]:
            st.session_state.lang_list.append(lang)
        st.session_state._lang_input = ""

    def _remove_lang(index):
        st.session_state.lang_list.pop(index)

    st.text_input(
        "Enter each language you know and press **Enter**:",
        key="_lang_input",
        on_change=_add_lang,
    )
    if st.session_state.lang_list:
        st.write("Languages entered:")
        for i, lang in enumerate(st.session_state.lang_list):
            name_col, remove_col = st.columns([4, 1])
            name_col.write(lang)
            remove_col.button("Remove", key=f"remove_lang_{i}_{lang}", on_click=_remove_lang, args=(i,))

    if len(st.session_state.lang_list) >= int(lang_count):
        if st.button("Continue"):
            known = [l.lower() for l in st.session_state.lang_list]
            if answered({"first language": first_lang}):
                if len(known) != int(lang_count):
                    st.warning(
                        f"You said you know {int(lang_count)} language(s) but listed {len(known)}. "
                        "Please correct the number or the list."
                    )
                elif first_lang.strip().lower() not in known:
                    st.warning("Please also add your first language to the list of languages you know.")
                else:
                    st.session_state.p["first_lang"]  = first_lang.strip()
                    st.session_state.p["lang_count"]  = int(lang_count)
                    st.session_state.p["lang_list"]   = st.session_state.lang_list[:]
                    advance()
                    st.rerun()
    else:
        remaining_langs = int(lang_count) - len(st.session_state.lang_list)
        st.info(f"Please enter {remaining_langs} more language(s).")



# Exit Poll 3 - language proficiency
elif step == "exit_poll_3":
    st.header("Follow Up Questions:")
    st.markdown(
        "For each language, rate your proficiency (1 = least, 5 = most proficient).*"
    )
    opts = ["1 - Least Proficient", "2", "3", "4", "5 - Most Proficient"]
    lang_prof = {}
    for lang in st.session_state.p.get("lang_list", []):
        lang_prof[lang] = st.radio(f"Proficiency in **{lang}**", opts, index=None, horizontal=True, key=f"prof_{lang}")
    if st.button("Continue") and answered({f"proficiency in {lang}": value for lang, value in lang_prof.items()}):
        st.session_state.p["lang_prof"] = lang_prof
        advance()
        st.rerun()



# Exit Poll 4 - language acquisition order
elif step == "exit_poll_4":
    st.header("Follow Up Questions:")
    st.markdown(
        "Rank each language by when you acquired it (1 = learnt first). "
        "If you learnt languages at the same time, give them the same number.*"
    )
    langs = st.session_state.p.get("lang_list", [])
    opts = [str(rank) for rank in range(1, len(langs) + 1)]
    lang_order = {}
    for lang in langs:
        lang_order[lang] = st.radio(f"Order for **{lang}**", opts, index=None, horizontal=True, key=f"order_{lang}")
    if st.button("Continue") and answered({f"order for {lang}": value for lang, value in lang_order.items()}):
        first = st.session_state.p.get("first_lang", "").lower()
        first_rank = next((rank for lang, rank in lang_order.items() if lang.lower() == first), None)
        if first_rank != "1":
            st.warning(f"Your first language ({st.session_state.p.get('first_lang')}) should be ranked 1.")
        else:
            st.session_state.p["lang_order"] = lang_order
            advance()
            st.rerun()



# Exit Poll 5 - location
elif step == "exit_poll_5":
    st.header("Follow Up Questions:")
    states_and_uts = [
        "Andaman and Nicobar Islands", "Andhra Pradesh", "Arunachal Pradesh", "Assam",
        "Bihar",
        "Chandigarh", "Chhattisgarh",
        "Dadra and Nagar Haveli and Daman and Diu", "Delhi",
        "Goa", "Gujarat",
        "Haryana", "Himachal Pradesh",
        "Jammu and Kashmir", "Jharkhand",
        "Karnataka", "Kerala",
        "Ladakh", "Lakshadweep",
        "Madhya Pradesh", "Maharashtra", "Manipur", "Meghalaya", "Mizoram",
        "Nagaland",
        "Odisha",
        "Puducherry",
        "Punjab",
        "Rajasthan",
        "Sikkim",
        "Tamil Nadu", "Telangana", "Tripura",
        "Uttar Pradesh", "Uttarakhand",
        "West Bengal",
    ]
    loc = st.selectbox(
        "Which state or union territory of India are you from?*", states_and_uts,
        index=None, placeholder="Choose a state or union territory",
    )
    if st.button("Continue") and answered({"state or union territory": loc}):
        st.session_state.p["location"] = loc
        advance()
        st.rerun()



# Exit Poll 6 - gender / age / education
elif step == "exit_poll_6":
    st.header("Follow Up Questions:")
    gender = st.radio("What is your gender?*", ["Male", "Female", "Other/Prefer not to say"], index=None, horizontal=True)
    age    = st.number_input("What is your age?*", min_value=18, max_value=100, step=1, value=None)
    edu    = st.number_input(
        "Years of formal education completed? (High school graduation = 12)*",
        min_value=0, max_value=30, step=1, value=None,
    )
    if st.button("Continue") and answered({"gender": gender, "age": age, "years of formal education": edu}):
        st.session_state.p.update(gender=gender, age=int(age), edu=int(edu))
        advance()
        st.rerun()



# Exit Poll 7 - dominant hand / alertness
elif step == "exit_poll_7":
    st.header("Follow Up Questions:")
    # Optional questions: None (left blank) is saved as is
    dom_hand = st.radio("What is your dominant hand?", ["Right", "Left", "Both"], index=None, horizontal=True)
    alert_tod = st.radio(
        "At what time of day do you feel most alert?",
        ["Morning", "Afternoon", "Evening", "Night", "No Difference"],
        index=None,
        horizontal=True,
    )
    if st.button("Continue"):
        st.session_state.p.update(dom_hand=dom_hand, alert_time=alert_tod)
        advance()
        st.rerun()



# Exit Poll 8 - extra info
elif step == "exit_poll_8":
    extra = st.text_area(
        "Is there any other information you would like to share that might have "
        "affected your performance? (e.g. lack of sleep, noisy environment)"
    )
    if st.button("Submit"):
        st.session_state.p["extra_info"] = extra
        advance()
        st.rerun()



# Saving
elif step == "saving":
    st.info("Saving your data, please wait...")
    doc = dict(st.session_state.p)
    doc["submitted_at"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    success = save_to_mongo(doc)
    if success:
        advance()
        st.rerun()
    else:
        st.error(
            "Error saving data. "
            "Please contact the researcher."
        )
        if st.button("Try Again"):
            st.rerun()



# Finis
elif step == "thank_you":
    st.balloons()
    st.title("Thank You!")
    st.markdown(
        "You have successfully completed the experiment. "
        "Your data has been saved securely."
    )
    st.markdown(
        "If you have any questions, feel free to contact the researcher at "
        "kssaisankalp.davey@research.iiit.ac.in"
    )