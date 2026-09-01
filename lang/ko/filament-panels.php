<?php

return [
    'pages' => [
        'dashboard' => [
            'title' => '대시보드',
        ],
    ],

    'resources' => [
        'actions' => [
            'create' => '생성',
            'edit' => '수정',
            'delete' => '삭제',
            'save' => '저장',
            'cancel' => '취소',
            'confirm' => '확인',
            'back' => '뒤로',
            'close' => '닫기',
        ],

        'tables' => [
            'actions' => [
                'edit' => '수정',
                'delete' => '삭제',
                'view' => '보기',
            ],
            'bulk_actions' => [
                'delete' => '선택 삭제',
            ],
            'empty' => '데이터가 없습니다.',
            'search' => '검색...',
            'filters' => [
                'apply' => '필터 적용',
                'reset' => '필터 초기화',
            ],
        ],

        'forms' => [
            'save' => '저장',
            'cancel' => '취소',
        ],
    ],

    'navigation' => [
        'dashboard' => '대시보드',
        'users' => '사용자',
        'companies' => '회사',
        'scans' => '스캔',
    ],

    'auth' => [
        'login' => [
            'title' => '로그인',
            'email' => '이메일',
            'password' => '비밀번호',
            'remember_me' => '로그인 상태 유지',
            'submit' => '로그인',
        ],
    ],
];
