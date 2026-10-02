<?php

use App\Support\EnvFile;

test('env example keeps secret placeholders empty', function () {
    $text = file_get_contents(dirname(__DIR__, 2).'/.env.example');

    expect($text)->toContain("APP_KEY=\n")
        ->and($text)->toContain("DB_PASSWORD=\n")
        ->and($text)->toContain("JWT_SECRET=\n")
        ->and($text)->not->toContain('base64:RtrLStZAvTnYkoIgg5q12')
        ->and($text)->not->toContain('wecarscan123')
        ->and($text)->not->toContain('P2qRCgGPEfwvlJI6ciOlJvG59socX2JP');
});

test('env file replaces secrets without leaving previous values', function () {
    $path = sys_get_temp_dir().'/wecarscan-env-'.uniqid().'.env';
    file_put_contents($path, implode("\n", [
        'APP_KEY=base64:old-key',
        'DB_PASSWORD=old-password',
        'JWT_SECRET=old-jwt-secret',
        '',
    ]));

    $env = new EnvFile($path);
    $env->set([
        'APP_KEY' => 'base64:new-key',
        'DB_PASSWORD' => 'new-password',
        'JWT_SECRET' => str_repeat('a', 64),
    ]);

    $text = file_get_contents($path);
    expect($text)->toContain('APP_KEY=base64:new-key')
        ->and($text)->toContain('DB_PASSWORD=new-password')
        ->and($text)->toContain('JWT_SECRET='.str_repeat('a', 64))
        ->and($text)->not->toContain('old-key')
        ->and($text)->not->toContain('old-password')
        ->and($text)->not->toContain('old-jwt-secret')
        ->and($env->get('JWT_SECRET'))->toHaveLength(64);

    unlink($path);
});
