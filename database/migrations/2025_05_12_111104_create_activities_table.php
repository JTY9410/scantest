<?php

use Illuminate\Database\Migrations\Migration;
use Illuminate\Database\Schema\Blueprint;
use Illuminate\Support\Facades\Schema;

return new class extends Migration
{
    /**
     * Run the migrations.
     */
    public function up(): void
    {
        Schema::create('activities', function (Blueprint $table) {
            $table->id();
            $table->foreignId('user_id')->nullable()->comment('사용자 아이디');
            $table->string('ip')->comment('IP 주소');
            $table->string('relation')->comment('연관 모델 클래스');
            $table->string('relation_type')->comment('액션 타입');
            $table->unsignedBigInteger('relation_id')->nullable()->comment('연관 모델 아이디');
            $table->json('changes')->nullable()->comment('변경사항');
            $table->string('message')->nullable()->comment('추가 메시지');
            $table->timestamps();

            $table->index(['relation', 'relation_id']);
            $table->index('relation_type');
        });
    }

    /**
     * Reverse the migrations.
     */
    public function down(): void
    {
        Schema::dropIfExists('activities');
    }
};
