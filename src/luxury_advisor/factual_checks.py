"""Small explicit checks for observed failures, never a semantic certification."""
import re


def latest_client_text(context):
    return next((m['text'] for m in reversed(context['request']['conversation_history'])
                 if m['speaker'] == 'client'), '')


def factual_contract(context):
    request=context['request'];text=latest_client_text(context)
    specific_care=request['scenario']=='post_purchase' and bool(re.search(
        r'起皮|破损|掉色|开裂|损坏|脱线|断裂|维修|换货|磨损|瑕疵|淋|湿|印子|污渍|松动|拉链.{0,6}卡',text))
    information_only=request['scenario']=='invitation' and bool(re.search(
        r'只告诉我.{0,20}(?:时间|地点)|把时间地点发来就好|只.{0,10}(?:时间地点|活动信息)',text))
    obligations=[]
    for name,pattern in [('weight',r'重量|多重'),('stock',r'现货|库存'),('origin',r'法国|产地'),
                         ('process',r'手工|制作方式'),('durability',r'耐用|年限')]:
        if re.search(pattern,text):obligations.append(name)
    return {'version':'factual-contract-1.0',
            'verified_prices':[{'product_id':p['id'],'price_cny':p['price_cny'],
                                'ref':f'product_information[{i}].price_cny'} for i,p in enumerate(context['product_information'])],
            'specific_care_issue':specific_care,'information_only':information_only,
            'explicit_question_topics':obligations,
            'instructions':[
                '金额须逐项核对verified_prices；保留真实目录价格，不能把预算或别处价差当本款价格。',
                '客户问题中每一个明确主题在每条候选中都要回答；未知事实使用需要核实的表述。',
                '具体湿水、污渍、磨损、拉链或连接处问题只提供门店核实下一步；日常干布轻拭不是这些问题的处理方案。',
                '历史顾问的免费服务说法需核实原记录和当前资格，省略自行定义旧政策、假定已拒绝处理或指定所需材料。',
                'information_only为true时只写已确认的活动安排，直接结束，省略邀请、回复要求、环境和满意程度推测。',
                '资料稀疏时保持简短真诚，省略虚构的喜欢文字、习惯和熟悉感。客户的兴趣不是已确认的活动议程。']}


def factual_findings(message,context,index):
    contract=factual_contract(context);findings=[]
    def add(code,feedback,excerpt,severity='block'):
        findings.append({'candidate_index':index,'code':code,'message':feedback,'excerpt':excerpt,'severity':severity})
    prices={p['price_cny'] for p in context['product_information']}
    for m in re.finditer(r'([0-9][0-9,，]{2,})\s*元',message):
        prefix=message[max(0,m.start()-12):m.start()];suffix=message[m.end():m.end()+9]
        if '预算' in prefix:continue
        if prices and (re.search(r'目录|标价|售价|定价|价格|按',prefix) or '目录价' in suffix):
            if int(m[1].replace(',','').replace('，','')) not in prices:
                add('catalog_price_mismatch','所写本款金额与当前产品目录不符；请逐字核对reply_brief.factual_contract.verified_prices后重写，保持真实定价条件。',m[0])
    text=latest_client_text(context)
    if 'weight' in contract['explicit_question_topics'] and 'stock' in contract['explicit_question_topics']:
        if not re.search(r'重量|多重',message) or not re.search(r'现货|库存',message):
            add('incomplete_compound_answer','客户同时问重量和库存，每一条都要明确这两项需要核实，省略用未询问的设计介绍代替。',message)
    if contract['specific_care_issue']:
        for m in re.finditer(r'自然晾干|通风|(?:按|吸)去.{0,5}水分|分开放稳|保持.{0,6}干燥|(?:用|拿|使用).{0,8}(?:擦|拭|涂|清洁)',message):
            prefix=message[max(0,m.start()-12):m.start()]
            if re.search(r'避免|省略|不要|需要核实',prefix):continue
            add('unverified_specific_care','这是具体污渍或损坏，资料只允许门店查看后给出处理建议。省略自行扩展的擦拭、干燥或拆放步骤；说明门店核实下一步即可。',m[0]);break
        if re.search(r'之前.{0,12}(?:是指|指日常|指的是)|没能.{0,10}兑现',message):
            add('invented_service_interpretation','历史服务表述需要核实，省略定义旧政策或假定本次已拒绝处理。',message)
    if contract['information_only']:
        extra=re.search(r'合心意|来坐坐|方便.{0,10}参加|告诉我是否|回我|是否方便|想邀|欢迎',message)
        if extra:add('event_information_only_drift','本次只要活动信息，写完已确认的时间、地点、内容就结束；省略邀请、满意程度推测和回复要求。',extra[0])
    guessed=re.search(r'(?:这场|您|你).{0,8}(?:应该|或许|一定|肯定).{0,8}(?:合心意|喜欢|满意)',message)
    if guessed:add('predicted_client_feeling','省略对客户满意或喜欢程度的推测，使用明确兴趣与已确认信息的联系。',guessed[0],'revise')
    no_taste=not context['request']['client']['preferences'] and not any(f['kind'] in ('preference','style') for f in context.get('client_memory',{}).get('facts',[]))
    if no_taste and not re.search(r'喜欢|偏好|习惯',text):
        invented=re.search(r'(?:您|你)(?:喜欢的文字|喜欢的风格|一贯的|一直喜欢)',message)
        if invented:add('unprovided_preference','本次资料没有该偏好，省略虚构喜欢的文字、风格或一贯习惯。',invented[0])
    return findings
