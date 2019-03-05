from rbr_rule import RBRRule
import os
from timeit import default_timer as dtimer
from utils import delete_dup
import  traceback

'''
This module translate the RBR generated by EthIR to SACO RBR.
It receives a list with rbr_rule instances.
'''
costabs_path = "/tmp/costabs/"
tmp_path = "/tmp/"

global pattern
pattern = ["PUSH1",
                   "DUP2",
                   "PUSH1",
                   "AND",
                   "ISZERO",
                   "PUSH2",
                   "MUL",
                   "SUB",
                   "AND",
                   "PUSH1",
                   "SWAP1",
                   "DIV"]

global svcomp
svcomp = {}

global verifier
verifier = ""

global exit_tag
exit_tag = 0

global init_loop
init_loop = 0

global init_globals
init_globals = False

global blocks2init
blocks2init = []

global exp_function
exp_function = False

global signextend_function
signextend_function = False

def rbr2c(rbr,execution,cname,scc,svc_labels,gotos,fbm):
    global svcomp
    global verifier
    global init_globals
    global blocks2init
    
    svcomp = svc_labels
    verifier = svc_labels.get("verify","")
    
    begin = dtimer()

    if fbm != []:
        init_globals = True
        blocks2init = fbm

    try:
        if gotos:
            heads, new_rules = rbr2c_gotos(rbr,scc)
        else:
            heads, new_rules = rbr2c_recur(rbr)

        if svcomp!={}:
            head_c , rule = initialize_globals(rbr)
            heads = "\n"+head_c+heads
            new_rules.append(rule)

        if exp_function:
            head, f = def_exp_function()
            heads = heads+head
            new_rules.append(f)

        if signextend_function:
            head, f = def_signextend_function()
            heads = heads+head
            new_rules.append(f)
            
        write_init(rbr,execution,cname)
        write(heads,new_rules,execution,cname)

        write_main(execution,cname)
        end = dtimer()
        print("C RBR: "+str(end-begin)+"s")
    except:
        #traceback.print_exc()
        raise Exception("Error in C_trnalsation",6)

def rbr2c_gotos(rbr,scc):
    heads = "\n"
    new_rules = []

    scc_unit = scc["unary"]
    scc_multiple = scc["multiple"]

    scc_ids = scc_unit+get_scc_labels(scc_multiple.values())
    
    heads_u, scc_unary_rules = compute_sccs_unary(rbr,scc_unit)
    heads_m, scc_multiple_rules = compute_sccs_multiple(rbr,scc_multiple)
    
    for rules in rbr: #it contains list of two elemtns (jumps) or unitary lists (standard rule)
        getId = rules[0].get_Id()
        type_rule = rules[0].get_type()

        if getId in scc_ids :
            if (heads_u.get(getId,-1)!=-1) and (type_rule == "block") :
                heads = heads+heads_u[getId]
                new_rules.append(scc_unary_rules[getId])

            elif (heads_m.get(getId,-1)!=-1) and (type_rule == "block"):
                heads = heads+heads_m[getId]
                new_rules.append(scc_multiple_rules[getId])
        else:
            if len(rules) == 2:
                head,new_rule = process_jumps(rules)
            else:
                head,new_rule = process_rule_c(rules[0])
                
            heads = heads+head
            new_rules.append(new_rule)
            
    return heads, new_rules

def rbr2c_recur(rbr):
    heads = "\n"
    new_rules = []
    
    for rules in rbr: #it contains list of two elemtns (jumps) or unitary lists (standard rule)

        if len(rules) == 2:
            head,new_rule = process_jumps(rules)
        else:
            head,new_rule = process_rule_c(rules[0])
                
        heads = heads+head
        new_rules.append(new_rule)

    return heads,new_rules

def compute_sccs_unary(rbr,scc_unit):
    global init_loop
    
    rules = {}
    heads = {}
    
    l = len(rbr)
    i = 0
    while i < l:
        r = rbr[i]
        if len(r) == 2:
            rid = r[0].get_Id()
            if rid in scc_unit:
                part_jump = translate_jump_scc(r,scc_unit,init_loop)
                i =i+1
                rule_main = rbr[i][0]
                head, part_main = translate_block_scc(rule_main,init_loop)
                init_loop+=1
                rule = part_main+"\n"+part_jump+"}"
                rules[rid] = rule
                heads[rid] = head
        else:
            rid = r[0].get_Id()
            if rid in scc_unit:
                head, part_main = translate_block_scc(r[0],init_loop)
                i+=1
                rule_jump = rbr[i]
                part_jump = translate_jump_scc(rule_jump,scc_unit,init_loop)
                init_loop+=1
                rule = part_main+"\n"+part_jump+"}"
                rules[rid] = rule
                heads[rid] = head

        i=i+1

    return heads, rules

def translate_jump_scc(r,scc,id_loop):

    jump1 = r[0]
    jump2 = r[1]

    instructions1 = jump1.get_instructions()
    instructions2 = jump2.get_instructions()

    call_if = filter_call(instructions1[0])
    call_else = filter_call(instructions2[0])

    if_id = get_called_block(call_if)

    if if_id in scc:
        guard = jump1.get_guard()
        cond = translate_conditions(guard)
        call_instr = call_else

    else:
        guard = jump2.get_guard()
        cond = translate_conditions(guard)
        call_instr = call_if
        
    label = "goto init_loop_"+str(id_loop)

    body = "\tif("+cond+"){\n"
    body = body+"\t\t"+label+"; }\n"
    body = body+"\t"+call_instr+";\n"

    return body

def translate_block_scc(rule,id_loop,multiple=False):
    stack_variables = get_input_variables(rule.get_index_invars())
    stack = map(lambda x: "int "+x,stack_variables)
    s_head = ", ".join(stack)

    head_c = "void " + rule.get_rule_name()+"("+s_head+");\n"
    head = "void " + rule.get_rule_name()+"("+s_head+"){\n"

    cont = rule.get_fresh_index()+1
    instructions = rule.get_instructions()
    has_string_pattern = rule.get_string_getter()
    new_instructions,variables = process_body_c(instructions,cont,has_string_pattern)

    if multiple:
        variables_d = get_variables_to_be_declared(stack_variables,variables,True)
    else:
        variables_d = get_variables_to_be_declared(stack_variables,variables)
        var_declarations = "\n"+variables_d+"\n"
    
    #To delete skip instructions
    new_instructions = filter(lambda x: not(x.strip().startswith("nop(")) and x!=";",new_instructions)

    new_instructions = new_instructions[:-1] #To delete the call instructions. It is always the last one.
    new_instructions = map(lambda x: "\t"+x,new_instructions)
    body = "\n".join(new_instructions)

    init_loop_label = "  init_loop_"+str(id_loop)+":\n"
    if rule.has_invalid() and svcomp!={}:
        source = rule.get_invalid_source()
        label = get_error_svcomp_label()+"; //"+source+"\n"
    else:
        label = ""

    if not multiple:
        rule_c = head+var_declarations+init_loop_label+body+label
        return head_c,rule_c
    else:
        return head_c,[head,init_loop_label+body+label],variables_d

def compute_sccs_multiple(rbr,scc):
    global init_loop
    global exit_tag
    
    rules = {}
    heads = {}
    exit_t = False
    body = ""
    exit_label = ""
    part_block = ""
    rbr_scc = filter_scc_multiple(rbr,scc.values())

    # for e in rbr_scc:
    #     print e.get_rule_name()    
    for s in scc:
        entry = get_rule_from_scc(s,rbr_scc)
        head, entry_part,vars_declaration = translate_block_scc(entry,init_loop,True)

        next_idx = get_rule_from_scc(s,rbr_scc,True,True)
        entry_jump,exit_block,next_block = translate_entry_jump(next_idx,rbr_scc)
        next_rule = get_rule_from_scc(next_block,rbr_scc)
        while(next_rule!=entry):
            vars_d, part, next_id,ex_t = translate_scc_multiple(next_rule,rbr_scc)
            exit_t = exit_t or ex_t
            part_block = part_block+part
            vars_declaration = vars_declaration+vars_d
            next_rule = get_rule_from_scc(next_id,rbr_scc)

        init_label = "\tgoto init_loop_"+str(init_loop)+";\n"
        end_label = "  end_loop_"+str(init_loop)+": \n"

        vars_declaration = delete_dup(vars_declaration)
        varsd_string = "\t".join(vars_declaration)
        
        body = entry_part[0]+"\n\t"+varsd_string+"\n"+entry_part[1]+"\n"
        body = body+entry_jump+part_block
        body = body+init_label+"\n"
        body = body+end_label
        
        if exit_t:
            exit_label = "  exit_"+str(exit_tag)+":\n\t ;\n"
            exit_tag+=1
            exit_t = False
            
        
        body = body+"\t"+exit_block+";\n"+exit_label+"}"
        rules[s] = body
        heads[s] = head
        # print entry_part
        # print entry_jump
        #print body
        init_loop+=1
        exit_label = ""
        part_block = ""
    return heads,rules
        

def translate_entry_jump(next_idx,scc):
    jump1 = scc[next_idx]
    jump2 = scc[next_idx+1]

    instructions1 = jump1.get_instructions()
    instructions2 = jump2.get_instructions()

    call_if = filter_call(instructions1[0])
    call_else = filter_call(instructions2[0])

    if_id = get_called_block(call_if)
    else_id = get_called_block(call_else)
    
    if if_id in scc:
        guard = jump2.get_guard()
        cond = translate_conditions(guard)
        call_instr = call_else
        next_block = if_id

    else:
        guard = jump1.get_guard()
        cond = translate_conditions(guard)
        call_instr = call_if
        next_block = else_id
        
    label = "goto end_loop_"+str(init_loop)

    body = "\tif("+cond+"){\n"
    body = body+"\t\t"+label+"; }\n"

    return body,call_instr,next_block

def translate_scc_multiple(rule,rbr_scc):

    exit_t = False
    
    stack_variables = get_input_variables(rule.get_index_invars())

    cont = rule.get_fresh_index()+1
    instructions = rule.get_instructions()
    has_string_pattern = rule.get_string_getter()
    new_instructions,variables = process_body_c(instructions,cont,has_string_pattern)
    
    variables_d = get_variables_to_be_declared(stack_variables,variables,True)
    #var_declarations = "\n"+variables_d+"\n"
    
    #To delete skip instructions
    new_instructions = filter(lambda x: not(x.strip().startswith("nop(")) and x!=";",new_instructions)

    called_instructions = new_instructions[-1]
    called_is_jump = called_instructions.startswith("j")

    if called_is_jump:
        jump_idx = get_rule_from_scc(rule.get_Id(),rbr_scc,True,True)
        part, next_block, exit_t = translate_jump_scc_multiple(jump_idx,rbr_scc)
    else:
        part = ""
        next_block = get_called_block(called_instructions)
    new_instructions = new_instructions[:-1] #To delete the call instructions. It is always the last one.
    new_instructions = map(lambda x: "\t"+x,new_instructions)
    body = "\n".join(new_instructions)
    body = body+"\n"+part
    
    return variables_d, body, next_block,exit_t

def translate_jump_scc_multiple(idx,scc):
    jump1 = scc[idx]
    jump2 = scc[idx+1]

    instructions1 = jump1.get_instructions()
    instructions2 = jump2.get_instructions()

    call_if = filter_call(instructions1[0])
    call_else = filter_call(instructions2[0])

    if_id = get_called_block(call_if)
    else_id = get_called_block(call_else)

    if_b = get_rule_from_scc(if_id,scc)
    
    if if_b in scc:
        guard = jump2.get_guard()
        cond = translate_conditions(guard)
        call_instr = call_else
        next_block = if_id

    else:
        guard = jump1.get_guard()
        cond = translate_conditions(guard)
        call_instr = call_if
        next_block = else_id
        
    label = "goto exit_"+str(exit_tag)

    body = "\tif("+cond+"){\n"
    body = body+"\t\t"+call_instr+";\n"
    body = body+"\t\t"+label+"; }\n"

    return body,next_block,True

def get_rule_from_scc(blockId,rbr_scc,jump=False,idx_r=False):
    if jump:
        r_aux = RBRRule(blockId,"jump")
    else:
        r_aux = RBRRule(blockId,"block")

    idx = rbr_scc.index(r_aux)
    
    if idx_r:
        return idx
    else:
        return rbr_scc[idx]

def get_scc_labels(scc):
    l = []
    for i in range(len(scc)):
        l = l+scc[i]
    return l
    
def filter_scc_multiple(rbr,scc):
    rules = []
    
    l = get_scc_labels(scc)

    for r in rbr:
        rule = r[0]
        rid = rule.get_Id()
        if rid in l:
            rules = rules+r

    return rules

def unbox_variable(var):
    open_pos = var.find("(")
    close_pos = var.find(")")
    if open_pos !=-1 and close_pos !=-1:
        new_var = var[:open_pos]+var[open_pos+1:close_pos]
    else:
        new_var = var
    return new_var

def check_declare_variable(var,variables):
    if var not in variables:
        variables.append(var)

def get_stack_variables(variables,l=False):
    stack_variables = filter(lambda x: x.startswith("s"),variables)
    idx_list = map(lambda x: int(x.strip()[1:]),stack_variables)
    sorted_idx = sorted(idx_list)
    rebuild_stack_variables = map(lambda x: "int s"+str(x)+";\n",sorted_idx)
    s_vars = "\t".join(rebuild_stack_variables)

    if l:
        return rebuild_stack_variables
    else:
        return s_vars

def get_rest_variables(variables,l=False):
    r_variables = filter(lambda x: not(x.startswith("s")),variables)
    sorted_variables = sorted(r_variables)
    rebuild_rvariables = map(lambda x: "int "+x+";\n",sorted_variables)
    r_vars = "\t".join(rebuild_rvariables)

    if l:
        return rebuild_rvariables
    else:
        return r_vars
    
def get_variables_to_be_declared(stack_variables,variables,l=False):
    vd = []
    for v in variables:
        if v not in stack_variables:
            vd.append(v)

    s_vars = get_stack_variables(vd,l)
    r_vars = get_rest_variables(vd,l)
    if l:
        return s_vars+r_vars
    else:
        return "\t"+s_vars+"\t"+r_vars
    
def get_input_variables(idx):
    in_vars = []
    for i in xrange(idx-1,-1,-1):
        var = "s"+str(i)
        in_vars.append(var)
    return in_vars

def translate_conditions(instr):

    if instr.startswith("gt"):
        arg1 = instr.split(",")[0].strip()
        arg2 = instr.split(",")[1].strip()
        var1 = unbox_variable(arg1[3:])
        var2 = unbox_variable(arg2[:-1])
        instr = var1+" > "+var2
    elif instr.startswith("sgt"):
        arg1 = instr.split(",")[0].strip()
        arg2 = instr.split(",")[1].strip()
        var1 = unbox_variable(arg1[3:])
        var2 = unbox_variable(arg2[:-1])
        instr = "(int)"+var1+" > "+"(int)"+var2
    elif instr.startswith("geq"):
        arg1 = instr.split(",")[0].strip()
        arg2 = instr.split(",")[1].strip()
        var1 = unbox_variable(arg1[4:])
        var2 = unbox_variable(arg2[:-1])
        instr = var1+" >= "+var2
    elif instr.startswith("lt"):
        arg1 = instr.split(",")[0].strip()
        arg2 = instr.split(",")[1].strip()
        var1 = unbox_variable(arg1[3:])
        var2 = unbox_variable(arg2[:-1])
        instr = var1+" < "+var2
    elif instr.startswith("slt"):
        arg1 = instr.split(",")[0].strip()
        arg2 = instr.split(",")[1].strip()
        var1 = unbox_variable(arg1[3:])
        var2 = unbox_variable(arg2[:-1])
        instr = "(int)"+var1+" < "+"(int)"+var2
    elif instr.startswith("leq"):
        arg1 = instr.split(",")[0].strip()
        arg2 = instr.split(",")[1].strip()
        var1 = unbox_variable(arg1[4:])
        var2 = unbox_variable(arg2[:-1])
        instr = var1+" <= "+var2
    elif instr.startswith("eq"):
        arg1 = instr.split(",")[0].strip()
        arg2 = instr.split(",")[1].strip()
        var1 = unbox_variable(arg1[3:])
        var2 = unbox_variable(arg2[:-1])
        instr = var1+" == "+var2
    elif instr.startswith("neq"):
        arg1 = instr.split(",")[0].strip()
        arg2 = instr.split(",")[1].strip()
        var1 = unbox_variable(arg1[4:])
        var2 = unbox_variable(arg2[:-1])
        instr = var1+" != "+var2
    else:
        instr = "Error in guard translation"

    return instr

def filter_call(call_instruction):
    block = call_instruction.strip()[5:-1].strip()
    pos_open = block.find("(")
    arguments = block[pos_open+1:-1]
    variables = arguments.split(",")
    s_vars = filter(lambda x: x.strip().startswith("s("),variables)
    s_vars = map(lambda x: unbox_variable(x.strip()),s_vars)
    
    s_string = ", ".join(s_vars)
    call = block[:pos_open]+"("+s_string+")"
    return call


def get_called_block(call_instruction):
    block = call_instruction.strip()[5:-1].strip()
    pos_open = block.find("(")
    block_id = block[:pos_open].strip()

    try:
        return int(block_id)

    except:
        return block_id

def process_jumps(rules):
    jump1 = rules[0]
    jump2 = rules[1]

    stack_variables = get_input_variables(jump1.get_index_invars())
    stack = map(lambda x: "int "+x,stack_variables)
    s_head = ", ".join(stack)

    head_c ="void " + jump1.get_rule_name()+"("+s_head+");\n"
    head = "void " + jump1.get_rule_name()+"("+s_head+"){\n"

    guard = jump1.get_guard()
    instructions1 = jump1.get_instructions()
    instructions2 = jump2.get_instructions()
    
    cond = translate_conditions(guard)

    call_if = filter_call(instructions1[0])
    call_else = filter_call(instructions2[0])

    body = "\tif("+cond+"){\n"
    body = body+"\t\t"+call_if+"; }\n"
    body = body+"\telse {\n"
    body = body+"\t\t"+call_else+"; }\n"
    end = "}\n"

    rule_c = head+body+end
    return head_c,rule_c

    
def process_rule_c(rule):
    stack_variables = get_input_variables(rule.get_index_invars())
    stack = map(lambda x: "int "+x,stack_variables)
    s_head = ", ".join(stack)

    head_c = "void " + rule.get_rule_name()+"("+s_head+");\n"
    head = "void " + rule.get_rule_name()+"("+s_head+"){\n"
    
    cont = rule.get_fresh_index()+1
    instructions = rule.get_instructions()
    has_string_pattern = rule.get_string_getter()
    new_instructions,variables = process_body_c(instructions,cont,has_string_pattern)
    
    variables_d = get_variables_to_be_declared(stack_variables,variables)
    var_declarations = "\n"+variables_d+"\n"
    
    #To delete skip instructions
    new_instructions = filter(lambda x: not(x.strip().startswith("nop(")) and x!=";",new_instructions)
    
    new_instructions = map(lambda x: "\t"+x,new_instructions)
    body = "\n".join(new_instructions)

    if rule.has_invalid() and svcomp!={}:
        source = rule.get_invalid_source()
        label = get_error_svcomp_label()+"; //"+source+"\n"
    else:
        label = ""
        
    end ="\n}\n"

    if (rule.get_Id() in blocks2init) and (svcomp!={}):
        init = "\tinit_globals();\n"
        rule_c = head+var_declarations+init+body+label+end
    else:
        rule_c = head+var_declarations+body+label+end
    
    return head_c,rule_c


def is_number(var):
    try:
        r = int(var)
        b = True
    except:
        r = -1
        b = False
        
    return b,r

def abstract_integer(var):
    b,r = is_number(var)
    new_var = ""

    if b:
        hexadec = hex(r)
        if len(hexadec)<=10:
            new_var = str(r)
        else:
            new_var = get_nondet_svcomp_label()
            
            # if hexadec[-1]=="L":
            #     left_h = hexadec[2:-9]
            #     right_h = hexadec[-9:-1]
            # else:
            #     left_h = hexadec[2:-8]
            #     right_h = hexadec[-8:]

            # fs = filter(lambda x: x!="f",left_h)
            
            # if len(fs)!= 0 and svcomp!={}:
            #     new_var = get_nondet_svcomp_label()
            # elif len(fs)!= 0 and svcomp=={}:
            #     new_var = "4294967295"
            # else:
            #     aux = "0x"+right_h
            #     new_var = str(int(aux,16))
            
    # if b and r>=4294967296:
    #     new_var = "4294967295"

    # elif b and r<4294967296:
    #     new_var = str(r)
    else:
        new_var = var
        
    return new_var
        
def compute_string_pattern(new_instructions):
    nop_inst = map(lambda x: "nop("+x+")",pattern)
    new_instructions = new_instructions+nop_inst
    return new_instructions

def process_body_c(instructions,cont,has_string_pattern):
    new_instructions = []
    variables = []
    #    instructions = filter(lambda x: x!= "", instructions)
    idx_loop = 0
    len_ins = len(instructions)
    
    #for instr in instructions:
    while(idx_loop<len_ins):
        instr = instructions[idx_loop]

        if idx_loop == 8 and has_string_pattern:
            new_instructions = compute_string_pattern(new_instructions)
            idx_loop = idx_loop+26
        else:
            cont = process_instruction(instr,new_instructions,variables,cont)
            idx_loop = idx_loop+1

    new_instructions = filter(lambda x: x!= "", new_instructions)
    return new_instructions,variables


def process_instruction(instr,new_instructions,vars_to_declare,cont):
    global signextend_function
    global exp_function
    
    if instr.find("nop(SIGNEXTEND")!=-1:
        pre_instr = new_instructions.pop()
        args = pre_instr.split("=")
        arg0 = args[0].strip()
        arg1 = args[1].strip()[:-1]
        pos = arg1[1:]
        pre_pos = int(pos)+1
        arg_bits = "s"+str(pre_pos)

        new_pre = arg0+" = signextend_eth("+arg1+", "+arg_bits+");"
        new_instructions.append(new_pre)
        signextend_function = True
        new = instr
        
    elif instr.find("nop(")!=-1:
        new = instr
        
    elif instr.find("call(",0)!=-1:
        call_block = instr[5:-1].strip()
        pos_open = call_block.find("(")
        block = call_block[:pos_open]
        
        args = call_block[pos_open+1:-1]
        vars_aux = args.split(",")
        stack_variables = filter(lambda x: x.startswith("s("),vars_aux)
        variables = map(lambda x : unbox_variable(x.strip()),stack_variables)
        new_variables = ", ".join(variables)
        new = block+"("+new_variables+")"

    elif instr.find("and(",0)!=-1:
        elems = instr.split("= and")
        arg0 = elems[0].strip()
        var0 = unbox_variable(arg0)

        arg12_aux = elems[1].strip()[1:-1]
        arg12 = arg12_aux.split(",")

        arg1 = arg12[0].strip()
        var1 = unbox_variable(arg1)

        arg2 = arg12[1].strip()
        var2 = unbox_variable(arg2)

        if (svcomp == {}) or (svcomp["verify"] == "cpa"):
            new = var0+" = "+ var1 +" & "+var2
        else:
        #if svcomp!={}:
            new = var0+" = "+get_nondet_svcomp_label()
        # else:
        #     new = var0+" = "+ var1 +" & "+var2

        check_declare_variable(var0,vars_to_declare)

    elif instr.find("xor(",0)!=-1:
        elems = instr.split("= xor")
        arg0 = elems[0].strip()
        var0 = unbox_variable(arg0)

        arg12_aux = elems[1].strip()[1:-1]
        arg12 = arg12_aux.split(",")

        arg1 = arg12[0].strip()
        var1 = unbox_variable(arg1)

        arg2 = arg12[1].strip()
        var2 = unbox_variable(arg2)


        if (svcomp == {}) or (svcomp["verify"] == "cpa"):
            new = var0+" = "+ var1 +" ^ "+var2
        else:
        #if svcomp!={}:
            new = var0+" = "+get_nondet_svcomp_label()
        # #if svcomp!={}:
        #     new = var0+" = "+ get_nondet_svcomp_label()

        # else:
        #     new = var0+" = "+ var1 +" ^ "+var2

        check_declare_variable(var0,vars_to_declare)
        
    elif instr.find("or(",0)!=-1:
        
        elems = instr.split("= or")
        arg0 = elems[0].strip()
        var0 = unbox_variable(arg0)

        arg12_aux = elems[1].strip()[1:-1]
        arg12 = arg12_aux.split(",")

        arg1 = arg12[0].strip()
        var1 = unbox_variable(arg1)

        arg2 = arg12[1].strip()
        var2 = unbox_variable(arg2)

        if (svcomp == {}) or (svcomp["verify"] == "cpa"):
            new = var0+" = "+ var1 +" | "+var2
        else:
            new = var0+" = "+get_nondet_svcomp_label()
        # if svcomp!={}:
        #     new = var0+" = "+get_nondet_svcomp_label()
        # else:
        #     new = var0+" = "+ var1 +" | "+var2
            
        check_declare_variable(var0,vars_to_declare)
        
    elif instr.find("not(",0)!=-1:
        elems = instr.split("= not")
        arg0 = elems[0].strip()
        var0 = unbox_variable(arg0)

        arg1 = elems[1].strip()[1:-1]
        var1 = unbox_variable(arg1)

        if (svcomp == {}) or (svcomp["verify"] == "cpa"):
            new = var0+" = ~"+ var1
        else:
            new = var0+" = "+get_nondet_svcomp_label()

        # if svcomp!={}:
        #     new = var0+" = "+get_nondet_svcomp_label()
        # else:
        #     new = var0+" = ~"+ var1

        check_declare_variable(var0,vars_to_declare)
        
    elif instr.find("gs(",0)!=-1:
        pos = instr.find("=")
        arg0 = instr[:pos].strip()
        var0 = unbox_variable(arg0)

        arg1 = instr[pos+1:].strip()
        var1 = unbox_variable(arg1)
        
        new = var0 +" = "+ var1
        check_declare_variable(var0,vars_to_declare)
        
    # elif instr.find("gl =",0)!=-1:
    #     pos = instr.find("=")
    #     arg0 = instr[:pos].strip()
    #     var0 = unbox_variable(arg0)

    #     arg1 = instr[pos+1:].strip()
    #     var1 = unbox_variable(arg1)
        
    #     new = var0 +" = " var1

    elif instr.find("l(l")!=-1:
        pos_local = instr.find("l(l")
        pos_eq = instr.find("=")
        if pos_eq < pos_local: #it is in the right
            arg0 = instr[:pos_eq].strip()
            var0 = unbox_variable(arg0)
            
            arg1 = instr[pos_eq+1:].strip()
            var1_aux = unbox_variable(arg1)
            var1 = var1_aux[1:]
            new = var0+" = "+var1
        else:
            arg0 = instr[:pos_eq].strip()
            var0_aux = unbox_variable(arg0)
            var0 = var0_aux[1:]

            if instr[pos_eq+1:].strip().startswith("fresh("):
                if svcomp!={}:
                    new = var0+" = "+get_nondet_svcomp_label()
                else:
                    new = var0+" = s"+str(cont)
                    check_declare_variable("s"+str(cont),vars_to_declare)
                    cont+=1
            else:
                arg1 = instr[pos_eq+1:].strip()
                var1 = unbox_variable(arg1)
                new = var0+" = "+var1
    
    elif instr.find("ls(",0)!=-1:
        pos = instr.find("=")
        arg0 = instr[:pos].strip()
        var0 = unbox_variable(arg0)

        arg1 = instr[pos+1:].strip()
        var1 = unbox_variable(arg1)
        
        new = var0 +" = "+ var1
        check_declare_variable(var0,vars_to_declare)
        
    # elif instr.find("ll =",0)!=-1:
    #     pos = instr.find("=")
    #     new = "l("+instr[:pos].strip()+") "+instr[pos:]        

    elif instr.find("fresh",0)!=-1:
        pos = instr.find("=")
        arg0 = instr[:pos].strip()
        var0 = unbox_variable(arg0)

        if svcomp!={}:
            new = var0+" = "+get_nondet_svcomp_label()
        else:
            new = var0+" = s"+str(cont)
            check_declare_variable("s"+str(cont),vars_to_declare)
            cont+=1
        
    elif instr.find("= eq(",0)!=-1:
        elems = instr.split("= eq")
        arg0 = elems[0].strip()
        var0 = unbox_variable(arg0)

        arg12_aux = elems[1].strip()[1:-1]
        arg12 = arg12_aux.split(",")

        arg1 = arg12[0].strip()
        var1 = unbox_variable(arg1)

        arg2 = arg12[1].strip()
        var2 = unbox_variable(arg2)

        new = var0+" = "+ var1 +" == "+var2
        check_declare_variable(var0,vars_to_declare)
        
    elif instr.find("= lt(",0)!=-1:
        elems = instr.split("= lt")
        arg0 = elems[0].strip()
        var0 = unbox_variable(arg0)

        arg12_aux = elems[1].strip()[1:-1]
        arg12 = arg12_aux.split(",")
        
        arg1 = arg12[0].strip()
        var1 = unbox_variable(arg1)

        arg2 = arg12[1].strip()
        var2 = unbox_variable(arg2)

        new = var0+" = "+ var1 +" < "+var2
        check_declare_variable(var0,vars_to_declare)

    elif instr.find("= slt(",0)!=-1:
        elems = instr.split("= slt")
        arg0 = elems[0].strip()
        var0 = unbox_variable(arg0)

        arg12_aux = elems[1].strip()[1:-1]
        arg12 = arg12_aux.split(",")
        
        arg1 = arg12[0].strip()
        var1 = unbox_variable(arg1)

        arg2 = arg12[1].strip()
        var2 = unbox_variable(arg2)

        new = var0+" = "+ var1 +" < "+var2
        check_declare_variable(var0,vars_to_declare)
        
    elif instr.find("= gt(",0)!=-1:
        elems = instr.split("= gt")
        arg0 = elems[0].strip()
        var0 = unbox_variable(arg0)

        arg12_aux = elems[1].strip()[1:-1]
        arg12 = arg12_aux.split(",")

        arg1 = arg12[0].strip()
        var1 = unbox_variable(arg1)

        arg2 = arg12[1].strip()
        var2 = unbox_variable(arg2)

        new = var0+" = "+ var1 +" > "+var2
        check_declare_variable(var0,vars_to_declare)

    elif instr.find("= sgt(",0)!=-1:
        elems = instr.split("= sgt")
        arg0 = elems[0].strip()
        var0 = unbox_variable(arg0)

        arg12_aux = elems[1].strip()[1:-1]
        arg12 = arg12_aux.split(",")

        arg1 = arg12[0].strip()
        var1 = unbox_variable(arg1)

        arg2 = arg12[1].strip()
        var2 = unbox_variable(arg2)

        new = var0+" = "+ var1 +" > "+var2
        check_declare_variable(var0,vars_to_declare)
        
    elif instr.find("g(",0)!=-1:
        pos = instr.find("=",0)
        arg0 = instr[:pos].strip()
        var0 = unbox_variable(arg0)

        arg1 = instr[pos+1:].strip()
        var1 = unbox_variable(arg1)

        new = var0+" = "+var1
        if var0.startswith("g"):
            check_declare_variable(var1,vars_to_declare)
        else:
            check_declare_variable(var0,vars_to_declare)
            
    elif instr.find("^",0)!=-1:
        pos = instr.find("=",0)
        arg0 = instr[:pos].strip()
        var0 = unbox_variable(arg0)

        arg12 = instr[pos+1:].strip().split("^")
        arg1 = arg12[0].strip()
        var1 = unbox_variable(arg1)
        
        arg2 = arg12[1].strip()
        var2 = unbox_variable(arg2)

        new = var0+" = exp_eth("+var1+", "+var2+")"
        exp_function = True
        # if svcomp!={}:
        #     new = var0+" = "+get_nondet_svcomp_label()
        # else:
        #     new = var0+" = s"+str(cont)
        #     check_declare_variable("s"+str(cont),vars_to_declare)
        #     cont+=1

        
    elif instr.find("byte",0)!=-1: # upper bound-> 255
        pos = instr.find("=",0)
        arg0 = instr[:pos].strip()
        var0 = unbox_variable(arg0)

        if svcomp!={}:
            new = var0+" = "+get_nondet_svcomp_label()
        else:
            new = var0+" = 255"

        check_declare_variable(var0,vars_to_declare)
        
    elif instr.find("sha",0)!=-1:
        pos = instr.find("=",0)
        arg0 = instr[:pos].strip()
        var0 = unbox_variable(arg0)

        if svcomp!={}:
            new = var0+" = "+get_nondet_svcomp_label()
        else:
            new = var0+" = s"+str(cont)
            check_declare_variable("s"+str(cont),vars_to_declare)
            cont+=1
        
    elif instr.find("+")!=-1:
        elems = instr.split("+")
        arg01 = elems[0].split("=")
        arg0 = arg01[0].strip()
        var0 = unbox_variable(arg0)

        arg1 = arg01[1].strip()
        var1 = unbox_variable(arg1)

        arg2 = elems[1].strip()
        var2 = unbox_variable(arg2)

        new = var0+" = "+var1+" + "+var2
        
    elif instr.find("-")!=-1:
        elems = instr.split("-")
        arg01 = elems[0].split("=")
        arg0 = arg01[0].strip()
        var0 = unbox_variable(arg0)

        arg1 = arg01[1].strip()
        var1 = unbox_variable(arg1)

        arg2 = elems[1].strip()
        var2 = unbox_variable(arg2)

        new = var0+" = "+var1+" - "+var2

    elif instr.find("*")!=-1:
        elems = instr.split("*")
        arg01 = elems[0].split("=")
        arg0 = arg01[0].strip()
        var0 = unbox_variable(arg0)

        arg1 = arg01[1].strip()
        var1 = unbox_variable(arg1)

        arg2 = elems[1].strip()
        var2 = unbox_variable(arg2)

        new = var0+" = "+var1+" * "+var2

    elif instr.find("/")!=-1:
        elems = instr.split("/")
        arg01 = elems[0].split("=")
        arg0 = arg01[0].strip()
        var0 = unbox_variable(arg0)

        arg1 = arg01[1].strip()
        var1 = unbox_variable(arg1)

        arg2 = elems[1].strip()
        var2 = unbox_variable(arg2)

        if verifier == "verymax":
            new = var0+" = "+ get_nondet_svcomp_label()
        else:
            new = var0+" = "+var1+" / "+var2

    elif instr.find("%")!=-1:
        elems = instr.split("%")
        arg01 = elems[0].split("=")
        arg0 = arg01[0].strip()
        var0 = unbox_variable(arg0)

        arg1 = arg01[1].strip()
        var1 = unbox_variable(arg1)

        arg2 = elems[1].strip()
        var2 = unbox_variable(arg2)

        if verifier == "verymax":
            new = var0+" = "+ get_nondet_svcomp_label()
        else:
            new = var0+" = "+var1+" % "+var2
                
    elif len(instr.split("=")) > 1:
        slices = instr.split("=")
        
        arg1 = slices[0].strip()
        arg2 = slices[1].strip()

        arg2 = abstract_integer(arg2)
        
        var1 = unbox_variable(arg1)
        var2 = unbox_variable(arg2)

        new = var1+" = "+var2
        check_declare_variable(var1,vars_to_declare)
        
    elif instr.find("skip")!=-1:
        new = ""
        
    else:
        new = instr
            
    new_instructions.append(new+";")
    return cont


def get_current_initloop():
    if init_loop == 0:
        return init_loop
    else:
        return init_loop-1

def get_nondet_svcomp_label():
    return "__VERIFIER_nondet_uint()"

def get_error_svcomp_label():
    return "ERROR: __VERIFIER_error()"

def add_svcomp_labels():
    labels = "";
    labels = labels+"extern int __VERIFIER_nondet_uint();\n"
    labels = labels + "extern void __VERIFIER_error();\n"

    return labels

def initialize_globals(rules):
    head_c = "void init_globals();"
    head = "void init_globals(){\n"
    
    vars_init = initialize_global_variables(rules)
    method = head+vars_init+"}\n"

    return head_c, method
    
def initialize_global_variables(rules):

    s = ""
    
    if(len(rules)>1):
        r = rules[1][0]
    else:
        r = rules[0][0]
            
    fields_id = r.get_global_arg()[::-1]
    bc_data = r.get_bc()
    locals_vars = sorted(r.get_args_local())[::-1]

    
    fields = map(lambda x: "\tg"+str(x)+" = __VERIFIER_nondet_uint()",fields_id)
    l_vars = map(lambda x: "\tl"+str(x)+" = __VERIFIER_nondet_uint()",locals_vars)
    bc = map(lambda x: "\t"+x+" = __VERIFIER_nondet_uint()",bc_data)

    if fields != []:
        s = s+";\n".join(fields)+";\n"

    if l_vars != []:
        s = s+";\n".join(l_vars)+";\n"

    if bc != []:
        s = s+";\n".join(bc)+";\n"
        
    return s

def write_init(rules,execution,cname):
    s = "\n"

    if svcomp!={}:
        s = add_svcomp_labels()
        s = s+"\n"
        
    if execution == None:
        name = costabs_path+"rbr.c"
    elif cname == None:
        name = costabs_path+"rbr"+str(execution)+".c"
    else:
        name = costabs_path+cname+".c"
    with open(name,"w") as f:
        if(len(rules)>1):
            r = rules[1][0]
        else:
            r = rules[0][0]
        fields_id = r.get_global_arg()[::-1]
        bc_data = r.get_bc()
        locals_vars = sorted(r.get_args_local())[::-1]
                                
        fields = map(lambda x: "int g"+str(x),fields_id)
        l_vars = map(lambda x: "int l"+str(x),locals_vars)
        bc = map(lambda x: "int "+x,bc_data)
        
        
        if fields != []:
            s = s+";\n".join(fields)+";\n"

        if l_vars != []:
            s = s+";\n".join(l_vars)+";\n"

        if bc != []:
            s = s+";\n".join(bc)+";\n"
        
        f.write(s)
        
    f.close()

def def_signextend_function():
    head = "int signextend_eth(int v0, int v1);\n"

    f = "int signextend_eth(int v0, int v1){\n"
    f = f+"\tif (v1 == 0 && v0 <= 0x7F){\n"+"\t\treturn v0;\n"+ "\t}"
    f = f+"else if (v1 == 0 && v0 >  0x7F){\n"+"\t\treturn v0 | 0xFFFFFF00;\n"+"\t}"
    f = f+"else if (v1 == 1 && v0 <= 0x7FFF){\n"+"\t\treturn v0;\n"+"\t}"
    f = f+"else if (v1 == 1 && v0 >  0x7FFF)  {\n"+"\t\treturn v0 | 0xFFFF0000;\n"+"\t}"
    f = f+"else if (v1 == 2 && v0 <= 0x7FFFFF) {\n"+"\t\treturn v0;\n"+"\t}"
    f = f+"else if (v1 == 2 && v0 >  0x7FFFFF) {\n"+"\t\treturn v0 | 0xFF000000;\n"+"\t}"
    f = f+"else if (v1 == 3) {\n"+"\t\treturn v0;\n"+"\t}"
    if svcomp.get("verify",-1) != -1:
        f = f+"else {\n"+"\t\treturn __VERIFIER_nondet_uint();\n"+"\t}\n"
    else:
        f = f+"else {\n"+"\t\tint v2;\n \t\treturn v2;\n"+"\t}\n"
        
    f = f+"}\n"

    return head,f

def def_exp_function():
    head = "int exp_eth (int v0, int v1);\n"

    f = "int exp_eth (int v0, int v1) {\n"

    f = f+"\tif (v1 == 0) return 1;\n"
    f = f+"\tif (v1 == 1) return v0;\n"
    f = f+"\tif (v1 == 2) return v0*v0;\n"
    f = f+"\tif (v1 == 3) return v0*v0*v0;\n"
    f = f+"\tif (v1 == 4) return v0*v0*v0*v0;\n"
    f = f+"\tif (v1 == 5) return v0*v0*v0*v0*v0;\n"
    f = f+"\tif (v1 == 6) return v0*v0*v0*v0*v0*v0;\n"
    f = f+"\tif (v1 == 7) return v0*v0*v0*v0*v0*v0*v0;\n"
    f = f+"\tif (v1 == 8) return v0*v0*v0*v0*v0*v0*v0*v0;\n"

    f = f+"\tint res = 1\n;"
    f = f+"\tfor (int i = 0; i < v1; i ++) {\n"
    f = f+"\t\tres = res * v0;\n"
    f = f+"\t}\n"
    f = f+"\treturn res;\n"
    f = f+"}"

    return head,f

def write_main(execution,cname):
    if execution == None:
        name = costabs_path+"rbr.c"
    elif cname == None:
        name = costabs_path+"rbr"+str(execution)+".c"
    else:
        name = costabs_path+cname+".c"

    with open(name,"a") as f:
        init = "\tinit_globals();"
        
        s = "\nint main(){\n"
        if svcomp!={} :
            s = s+"\n"+init+"\n"
        s = s+"\tblock0();\n"
        s = s+"\treturn 0;\n}"
        f.write(s)
    f.close()

def write(head,rules,execution,cname):
    
    # if "costabs" not in os.listdir("/tmp/"):
    #     os.mkdir("/tmp/costabs/")

    if execution == None:
        name = costabs_path+"rbr.c"
    elif cname == None:
        name = costabs_path+"rbr"+str(execution)+".c"
    else:
        name = costabs_path+cname+".c"
    with open(name,"a") as f:
        f.write(head+"\n")
        
        for rule in rules:
            f.write(rule+"\n")

    f.close()
