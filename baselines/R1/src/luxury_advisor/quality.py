"""Scene-specific writing briefs and deliberately limited, inspectable rule checks.

These checks flag a few known defects. They never certify factual correctness,
personalization, respect, or a human-calibrated content quality score.
"""

import json
import re
from difflib import SequenceMatcher
from pathlib import Path

from luxury_advisor.models import CandidateSet

REVIEW_VERSION = "reply-rules-0.4.2"


def _price_only_request(request: dict) -> dict | None:
    statements = [(i, item["text"]) for i, item in enumerate(request["conversation_history"]) if item["speaker"] == "client"]
    if not statements:
        return None
    index, text = statements[-1]
    pattern = r"(?:只(?:问|报|说|告诉|回答|需(?:要)?|想知道|想了解|要)|仅(?:需(?:要)?|问|报|回答)).{0,30}?(?:多少钱|价格|报价|价钱|折扣|打折|同价)"
    for match in re.finditer(pattern, text):
        prefix = re.split(r"[，,。；;！？!?\n]", text[:match.start()])[-1]
        if re.search(r"(?:不要|不用|不必|不是|并非|无需|别)\s*$", prefix):
            continue
        # “只要价格合适，我就考虑” is a condition, not a request for price only.
        if re.match(r"只要.{0,12}(?:合适|合理|便宜|预算内|能接受)", text[match.start():]):
            continue
        return {"ref": f"request.conversation_history[{index}]", "value": text}
    return None


def build_price_value_brief(context: dict, data_dir: Path, evidence: list[dict]) -> dict:
    """Ground optional benefit language in the current catalog, never extra claims.

    The LLM must still check current intent and each note's applicability. We do
    not infer interests by keyword, score feelings, or assert that a benefit fits.
    """
    library = json.loads((data_dir / "product_value_notes.json").read_text(encoding="utf-8"))
    options, omitted = [], []
    products = context["product_information"]
    for note in library["product_notes"]:
        for index, product in enumerate(products):
            if product["id"] != note["product_id"]:
                continue
            facts = []
            for fact in note["facts"]:
                field, value = fact["field"], fact["value"]
                if field not in ("features", "colors", "material"):
                    break
                actual = product.get(field)
                if isinstance(actual, list) and value in actual:
                    ref = f"product_information[{index}].{field}[{actual.index(value)}]"
                elif isinstance(actual, str) and actual == value:
                    ref = f"product_information[{index}].{field}"
                else:
                    break
                facts.append({"ref": ref, "value": value})
            if not facts or len(facts) != len(note["facts"]):
                omitted.append(note["id"])
                continue
            options.append({
                "id": note["id"], "product_id": product["id"], "product_name": product["name"],
                "verified_catalog_facts": facts,
                "use_only_when": note["use_when"], "possible_connection": note["experience_connection"],
            })
    return {
        "version": library["version"], "status": library["status"],
        "notice": library["notice"], "customer_evidence": evidence,
        "selection_rules": library["selection_rules"], "optional_connections": options,
        "editorial_examples": library["editorial_examples"],
        "omitted_stale_note_ids": omitted,
        "review_questions": [
            "每条是否回答了本次价格问题，并遵从客户最新的预算和沟通边界？",
            "价值表达落在哪句客户原话和哪项已核实产品事实？资料不足时是否恰当询问或省略？",
            "是否让人感到自己的习惯、审美或心意被认真回应，语言自然且有画面？",
            "是否避免身份施压、虚构故事和替客户宣判值不值得？",
        ],
        "evaluation_status": "not_evaluated",
        "response_mode": "personal_value_or_explore",
    }


def build_reply_brief(context: dict, data_dir: Path) -> dict:
    playbooks = json.loads((data_dir / "reply_playbooks.json").read_text(encoding="utf-8"))
    request = context["request"]
    scene = playbooks["scenes"][request["scenario"]]
    memory = context.get("client_memory", {})
    evidence = []
    for index, item in enumerate(request["conversation_history"]):
        if item["speaker"] == "client":
            evidence.append({"ref": f"request.conversation_history[{index}]", "topic": "本次客户表态", "value": item["text"]})
    # A current client statement has priority; memory evidence remains available in full context.
    evidence = evidence[-3:]
    for fact in memory.get("facts", []):
        if fact["kind"] in ("constraint", "style", "intent") or (request["scenario"] == "price_objection" and fact["kind"] == "preference"):
            evidence.append({"ref": f"client_memory.facts:{fact['id']}", "topic": fact["topic"], "value": fact["value"]})
    if not evidence or request["scenario"] == "price_objection":
        for index, value in enumerate(request["client"]["preferences"][:4]):
            if not any(item["value"] == value for item in evidence):
                evidence.append({"ref": f"request.client.preferences[{index}]", "topic": "已提供偏好", "value": value})
    # This is a focus aid, not an exhaustive retrieval filter or proof of actual use.
    brief = {
        "version": playbooks["version"], "scenario_name": scene["name"], "goal": scene["goal"],
        "approaches": scene["approaches"], "writing_rules": playbooks["shared_rules"] + scene["rules"],
        "focus_evidence": evidence[:8], "editorial_example": scene["example"],
        "example_status": playbooks["status"],
        "priority": "本次明确诉求与沟通边界 → 适用的个人偏好与表达风格 → 必要产品事实；基础人口资料不代替偏好。",
    }
    # Curated policy only: raw reviews, uncertain labels and sample facts never
    # become general instructions or facts about the currently selected client.
    calibration = json.loads((data_dir / "reply_calibration.json").read_text(encoding="utf-8"))
    brief["writing_rules"] += calibration["writing_rules"] + calibration["scene_rules"].get(request["scenario"], [])
    brief["calibration"] = {
        "version": calibration["version"], "status": calibration["status"],
        "source_sha256": calibration["source"]["sha256"],
        "reviewed_scene_groups": calibration["coverage"]["scene_groups"],
        "current_scene_human_reviewed": request["scenario"] in calibration["coverage"]["scene_groups"],
        "examples": [item for item in calibration["examples"] if item["scenario"] == request["scenario"]][:2],
        "notice": "示例只供比较写法；human_accepted_in_its_case仅代表原案例内认可，assistant_adapted_not_user_reviewed仍待人审。人物、引文和产品事实不得迁移至当前客户。",
    }
    if request["scenario"] == "price_objection":
        brief["price_value_brief"] = build_price_value_brief(context, data_dir, evidence)
        price_only = _price_only_request(request)
        if price_only:
            brief["goal"] = "遵从客户本次仅答价格的要求，只给实际价格和当前定价条件，简短结束。"
            brief["approaches"] = [
                {"title": "金额与条件", "intent": "一两句直接说明实际价格及按标价提供。"},
                {"title": "产品与价格", "intent": "用另一种短句说明同样价格条件，保持信息完整。"},
                {"title": "简短答复", "intent": "仍只回答同一价格问题，省略祝愿、劝导、设计细节和问题。"},
            ]
            brief["focus_evidence"] = [{**price_only, "topic": "本次仅答价格的明确要求"}]
            value = brief["price_value_brief"]
            value["response_mode"] = "price_only"
            value["customer_evidence"] = brief["focus_evidence"]
            value["optional_connections"] = []
            value["editorial_examples"] = [item for item in value["editorial_examples"] if item.get("response_mode") == "price_only"]
            value["response_contract"] = {
                "source": price_only, "allowed_content": ["称呼（可选）", "实际价格", "本次真实定价条件"],
                "instruction": "本次每条只用一两句答价格，控制在60字内直接结束。旧有文雅偏好在本次让位于客户明确要求；省略祝愿、意象、评价、劝导、追问与价值介绍。产品或价格未知时先作必要澄清，禁止编造。",
            }
    client_statements = [item["text"] for item in request["conversation_history"] if item["speaker"] == "client"]
    client_statements += [item["text"] for item in memory.get("interactions", []) if item["speaker"] == "client"]
    client_statements += list(request["scenario_details"].values())
    if request["scenario"] == "post_purchase" and any(re.search(r"起皮|破损|掉色|开裂|损坏|脱线|断裂|维修|换货|退货|瑕疵", text) for text in client_statements):
        brief["context_mode"] = "product_issue"
        brief["goal"] = "先回应产品问题和客户提出的处理诉求，说明需要核实的边界，减少解决问题的负担。"
        brief["approaches"] = [
            {"title": "先回应问题", "intent": "回应具体不便，直接回答处理诉求，说明核实步骤。"},
            {"title": "说清核实边界", "intent": "仍先回应同一问题，清楚区分未知原因与未确认的处理资格。"},
            {"title": "减轻处理负担", "intent": "用另一种自然短句交代必要下一步，不添加自行处理建议。"},
        ]
    return brief


def _positive_matches(pattern: str, message: str):
    """Ignore straightforward local denials; complex language still needs a person."""
    for match in re.finditer(pattern, message, flags=re.IGNORECASE):
        prefix = re.split(r"[，,。；;！？!?\n]", message[:match.start()])[-1][-14:]
        prefix = re.split(r"但是|不过|可是|然而|但", prefix)[-1]
        if re.search(r"不能|无法|没有|无权|不承诺|不保证|不代表|尚不能|不要|不建议|未经确认|需(?:要)?先核实|[不未]$", prefix):
            continue
        yield match


def review_candidates(candidates: CandidateSet, context: dict) -> dict:
    request = context["request"]
    scene = request["scenario"]
    findings = []

    def add(index, code, message, excerpt, severity="revise"):
        findings.append({"candidate_index": index, "code": code, "message": message, "excerpt": excerpt, "severity": severity})

    for index, candidate in enumerate(candidates.candidates, 1):
        message = candidate.message
        if re.search(r"[，、：；,:;]$", message):
            add(index, "unfinished_sentence", "请写完句子，以完整自然的语意收尾，省略停在逗号、冒号或分号的残句。", message[-20:], "block")
        # Deliberately phrase-based: 不凡/不同/不错/不锈钢 are not denials.
        # This catches familiar forms, not all Chinese negation or inference.
        negative = re.search(r"不能|无法|无权|没有|不是|不必|不用|无需|无须|不要|不可以|不方便|不合适|不适合|不需要|不建议|不允许|不提供|不支持|不接受|不代表|不保证|不承诺|不打扰|不回复|不够|不如|不想|没法|没办法|做不到|给不了|办不了|跟不上", message)
        if negative:
            add(index, "negative_framing", "改用肯定式表达：说清已知条件、可行行动或核实事项，仍直接回答原问题，保留真实业务边界。", negative.group())
        inference = re.search(r"(?:您|你)(?:最近|这阵子|平时)?(?:一定|肯定|想必|应该|大概|可能|也许|似乎).{0,12}|(?:以您|像您|凭您).{0,16}(?:品味|审美|身份|职位|年龄|职业)|(?:一定|肯定|必然).{0,5}(?:适合您|适合你|符合您的审美)", message)
        if inference:
            add(index, "client_inference", "去掉替客户判断的推测，改为已确认的需求与事实之间的具体联系。", inference.group())
        signature = re.search(r"(?:^|\n)\s*(?:序隅\s*(?:XUYU)?|XUYU)\s*[·|｜]?\s*(?:客户)?顾问\s*$", message, re.IGNORECASE)
        if signature:
            add(index, "unrequested_signature", "去掉模板式顾问落款，让正文保持自然私聊。", signature.group().strip())
        if "您随意" in message:
            add(index, "awkward_distance", "“您随意”容易显得疏离，换成自然、有分寸的结束。", "您随意")
        if scene == "greeting":
            for match in _positive_matches(r"(?:来|到|莅临)(?:我们)?店(?:里)?|(?:看看|了解)(?:这款|新品|产品)|(?:保养|护理)(?:的事|建议|问题)", message):
                add(index, "greeting_drift", "祝福保持单一目的，去掉无关的到店、产品或保养引导。", match.group())
                break
        if context.get("reply_brief", {}).get("context_mode") == "product_issue":
            for match in _positive_matches(r"(?:用|拿|使用).{0,8}(?:擦|涂|清洁)|(?:擦拭|擦一擦|涂抹)", message):
                add(index, "unverified_issue_remedy", "已有产品问题时，不把常规擦拭或自行处理当成解决方案。", match.group())
                break
        if len(re.findall(r"[?？]", message)) > 1:
            add(index, "too_many_questions", "一次只问一个对当前决定最有帮助的问题。", message)
        for match in _positive_matches(r"(?:可以|可为您|会为您|保证|承诺|直接|一定能).{0,6}(?:免费(?:维修|更换|换新)|[一二三四五六七八九1-9](?:点[一二三四五六七八九1-9])?折|同价|价格匹配)|终身免费保修|永久保修|绝不褪色|保证(?:有现货|保值|升值)", message):
            add(index, "unsupported_commitment", "出现未经授权的价格或服务保证，需要先改写并核实。", match.group(), "block")
        if scene == "price_objection":
            latest_client = next((m["text"] for m in reversed(request["conversation_history"]) if m["speaker"] == "client"), "")
            if re.search(r"喜欢|在意|日常|天天|平日|通勤|只放|预算", latest_client) and re.search(r"[？?]", message):
                add(index, "price_redundant_question", "客户已明确使用诉求，请用陈述完成价值说明，省略再次追问已知用途或偏好。", message)
            deferred = re.search(r"(?:值不值得|值不值|是否值得).{0,24}(?:使用后|日常使用|慢慢体会|用过|用后)|(?:使用后|用过|用后).{0,20}(?:值不值|是否值得)", message)
            if deferred:
                add(index, "deferred_value_judgment", "现在回应购买前的价值判断，连接客户已确认的用途与产品细节，省略让客户购买后再体会是否值得的表达。", deferred.group())
            generic = re.search(r"这个问题很实际|您的问题很实际|这个问题问得好|我会如实说明|我如实说明|让我为您说明", message)
            if generic:
                add(index, "price_self_commentary", "直接回答客户的价格与价值问题，省略自我点评和对问题的泛化评价。", generic.group())
            value_brief = context.get("reply_brief", {}).get("price_value_brief", {})
            if value_brief.get("response_mode") == "price_only":
                body = message.replace(request["client"]["preferred_name"], "")
                drift = re.search(r"愿|祝您|希望您|心意|从容|慢慢|节奏|选到|舒心|用着|入手|犒劳|匠心|手工|您心里", body)
                if drift or (context["product_information"] and re.search(r"[?？]", body)):
                    add(index, "price_only_drift", "客户本次明确只要价格，请只保留实际价格和定价条件，去掉祝愿、价值介绍、劝导或追问。", drift.group() if drift else body, "block")
            for pressure in _positive_matches(r"(?:以|凭)您的(?:身份|身价|地位)|真正懂(?:奢侈品|品质)的人|(?:证明|彰显|体现)(?:您|您的)?(?:身份|身价|地位)|(?:犒劳|对得起)自己.{0,6}(?:就该|就要|必须)", message):
                add(index, "status_pressure", "价值感应来自客户明确的在意点与产品事实，去掉身份攀比和购买压力。", pressure.group(), "block")
                break
            commentary = re.search(r"我(?:把|将).{0,12}如实说明", message)
            if commentary:
                add(index, "price_self_commentary", "直接说价格与客户相关的价值，省略对自己如何说明价格的点评。", commentary.group())
            blunt = re.search(r"价格条件就是这样|就是这个价", message)
            if blunt:
                add(index, "blunt_price_boundary", "直接说明实际标价与价格条件即可，去掉生硬的终止式口吻。", blunt.group())
            latest = [item["text"] for item in request["conversation_history"] if item["speaker"] == "client"]
            if latest and re.search(r"折|同价|便宜|贵|价格|价差", latest[-1]) and not re.search(r"价|折|预算|贵|优惠|费用", message):
                add(index, "price_question_unanswered", "这一条也应正面回应价格问题，不能用推荐或到店绕开。", message)
    name = request["client"]["preferred_name"]
    normalized = [re.sub(r"[\W_]+", "", item.message.replace(name, "")) for item in candidates.candidates]
    for left in range(3):
        for right in range(left + 1, 3):
            # Very short greetings legitimately share vocabulary; don't lengthen them for diversity.
            if min(len(normalized[left]), len(normalized[right])) >= 24 and SequenceMatcher(None, normalized[left], normalized[right]).ratio() >= .90:
                add(right + 1, "near_duplicate", f"与第{left + 1}条措辞高度接近，请确认是否提供不同的有用选择。", "", "review")
    return {
        "version": REVIEW_VERSION,
        "status": "needs_review" if findings else "no_rule_flags",
        "copy_blocked": any(item["severity"] == "block" for item in findings),
        "findings": findings,
        "automatic_rewrite_count": 0,
        "coverage_notice": "仅检查列明的常见短语；未发现规则问题不代表已消除全部否定表达、推测或事实问题。",
        "not_checked": ["完整事实与承诺核实", "深层个人化", "真实尊重感与情绪体验", "文化引文准确性", "三条策略的语义差异"],
        "human_review": "not_reviewed", "semantic_score": None,
    }
