function fish_prompt
    set -l last_status $status
    if test $last_status != 0
        set arrow_color "red"
    else
        set arrow_color "green"
    end

    if fish_is_root_user
        set arrow "#"
    else
        set arrow "➜"
    end

    echo -s -n \
        (set_color green) (prompt_hostname) ' ' \
        (set_color $arrow_color) $arrow '  ' \
        (set_color -o cyan) (prompt_pwd | path basename) \
        (set_color normal) ' '
end

function fish_right_prompt
    set -l last_status $status
    if test $last_status != 0
        set status_str "[$last_status]"
    else if test $last_status -ge 129 -a $last_status -le 255
        set -l sig (math $last_status - 128)
        set -l sig_name (kill -l $sig 2>/dev/null)
        if test -n "$sig_name"
            set status_str "[SIG$sig_name]"
        end
    end

    if test $CMD_DURATION -ge 1000
        set duration_sec (math --scale 2 $CMD_DURATION / 1000)
        set duration_str "[$duration_sec s]"
    else if test $CMD_DURATION -gt 0
        set duration_str "[$CMD_DURATION ms]"
    end

    echo -s -n \
        (set_color red) $status_str ' ' \
        (set_color blue) $duration_str
end
