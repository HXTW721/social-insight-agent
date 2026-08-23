import json
from datetime import date

from src.llm.client import chat


def report(topic: str, plan: dict, analyses: list[dict], visual_insight: str = "") -> str:
    today = date.today().strftime("%Y-%m-%d")
    plan_text = json.dumps(plan, ensure_ascii=False, indent=2)
    analyses_text = "\n\n".join(
        f"【{a.get('dimension', '未命名维度')}】{a.get('conclusion', '')}\n"
        f"来源链接: {', '.join(a.get('sources', []))}"
        for a in analyses
    )
    visual_text = f"\n\n视觉/美术风格分析：\n{visual_insight}" if visual_insight else ""
    prompt = f"""你是报告撰写者（Reporter）。请基于研究计划和各维度分析，产出一份 Markdown 格式的行情洞察报告。

今天是 {today}。报告日期一律写 {today}，不要编造其它日期、作者、部门或机构名。

研究主题：{topic}

研究计划：
{plan_text}

各维度分析（每个分析末尾附带了 sources 来源链接）：
{analyses_text}
{visual_text}

报告要求：
1. 结构清晰，分章节
2. 引用结论时，只使用各维度分析里 sources 提供的真实链接；禁止编造链接或来源名
3. 如果提供了视觉/美术风格分析，单独作为一个章节
4. 结尾给一个总结表格 + 核心结论
"""
    messages = [{"role": "user", "content": prompt}]
    return chat(messages, temperature=0.4, max_tokens=8000)
