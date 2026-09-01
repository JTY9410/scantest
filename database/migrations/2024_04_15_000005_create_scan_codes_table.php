<?php

use Illuminate\Database\Migrations\Migration;
use Illuminate\Database\Schema\Blueprint;
use Illuminate\Support\Facades\Schema;

return new class extends Migration
{
    public function up(): void
    {
        Schema::create('scan_codes', function (Blueprint $table) {
            $table->id()->comment('아이디');
            $table->enum('type', ['ev', 'ice'])->comment('종류');
            $table->foreignId('scan_id')->comment('스캔 아이디');
            $table->foreignId('code_id')->comment('코드 아이디');
            $table->timestamps();
            $table->softDeletes();

            // 외래키 제약조건
            $table->foreign('scan_id')->references('id')->on('scans')->onDelete('cascade');
            $table->foreign('code_id')->references('id')->on('codes')->onDelete('cascade');
        });
    }

    public function down(): void
    {
        Schema::dropIfExists('scan_codes');
    }
};
